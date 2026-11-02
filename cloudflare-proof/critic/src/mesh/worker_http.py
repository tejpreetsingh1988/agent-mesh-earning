"""Async HTTP for hosts where synchronous urllib cannot work.

Root cause, proven Nov 1, 2026: the Scout Worker (v1) returned
NOT_REPORTED_YET for GOOGL because its EDGAR fetch died in-Worker
with "Remote end closed connection without response". Cloudflare's
own docs say Python Workers do not support synchronous requests —
no worker threads, no synchronous XHR — so stdlib urllib, which
every mesh fetcher uses, cannot work there. The supported route
is async fetch via Pyodide's pyfetch (documented for Python
Workers: "Use js.fetch or use pyodide.http for networking").

This module is the single async fetch layer:
- In a Worker (pyodide importable): pyfetch, which rides the
  Worker's fetch. Server-side fetch has no CORS restriction.
- Anywhere else (local dev, tests, Docker): the same urllib
  call on a worker thread via asyncio.to_thread — identical
  bytes, no behaviour change for non-Worker hosts.

Non-200 responses raise WorkerHTTPError(status, url) so callers
can mirror urllib's HTTPError handling (the transcript
candidate loop treats a miss as "try the next URL", not data).
"""
import asyncio
import gzip
import json
import urllib.error
import urllib.request

__all__ = ["WorkerHTTPError", "fetch_bytes", "fetch_json", "fetch_text", "post_json"]


class WorkerHTTPError(Exception):
    """A non-200 HTTP response. Mirrors urllib.error.HTTPError's
    status-carrying shape closely enough for callers to branch on."""

    def __init__(self, status: int, url: str):
        super().__init__(f"HTTP {status} for {url}")
        self.code = status
        self.url = url


def _pyfetch():
    """Return pyodide.http.pyfetch, or None outside a Worker."""
    try:
        from pyodide.http import pyfetch  # type: ignore
        return pyfetch
    except ImportError:
        return None


async def fetch_bytes(url: str, headers: dict | None = None) -> bytes:
    pyfetch = _pyfetch()
    if pyfetch is not None:
        resp = await pyfetch(url, headers=headers or {})
        if resp.status != 200:
            raise WorkerHTTPError(resp.status, url)
        data = await resp.bytes()
        return bytes(data)
    def _sync() -> bytes:
        req = urllib.request.Request(url, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return raw
        except urllib.error.HTTPError as e:
            # Translate so callers see one error type on both paths.
            raise WorkerHTTPError(e.code, url) from None
    return await asyncio.to_thread(_sync)


async def fetch_json(url: str, headers: dict | None = None):
    return json.loads(await fetch_bytes(url, headers=headers))


async def fetch_text(url: str, headers: dict | None = None) -> str:
    return (await fetch_bytes(url, headers=headers)).decode("utf-8", errors="ignore")


async def post_json(url: str, payload: dict, headers: dict | None = None):
    """POST a JSON body, return the decoded JSON response. Same
    two transports as fetch_bytes: pyfetch in a Worker, urllib
    on a thread elsewhere. Non-200 raises WorkerHTTPError, so
    agent-call failures surface as errors, not as data."""
    body = json.dumps(payload).encode("utf-8")
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    pyfetch = _pyfetch()
    if pyfetch is not None:
        resp = await pyfetch(url, method="POST", headers=hdrs, body=body)
        if resp.status != 200:
            raise WorkerHTTPError(resp.status, url)
        return await resp.json()
    def _sync():
        req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            raise WorkerHTTPError(e.code, url) from None
    return await asyncio.to_thread(_sync)
