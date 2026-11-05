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


# Batch 35 (Nov 5, 2026): retry policy for fetch_bytes. EDGAR
# rate-limits the Workers' shared egress IPs (HTTP 429); a
# single 429 used to kill a whole fetch (Scout, fine-print and
# KPI fetches all start with company_tickers.json). Three
# attempts with backoff: worst case ~3x30s + 10s delays, bounded
# by each caller's own deadline (the fine-print step's 180s,
# the Orchestrator's 300s agent timeout).
FETCH_RETRY_ATTEMPTS = 3
FETCH_RETRY_DELAYS_S = (2, 8)
FETCH_ATTEMPT_TIMEOUT_S = 30
_RETRYABLE_STATUS = (429, 500, 502, 503, 504)


def _pyfetch():
    """Return pyodide.http.pyfetch, or None outside a Worker."""
    try:
        from pyodide.http import pyfetch  # type: ignore
        return pyfetch
    except ImportError:
        return None


async def fetch_bytes(url: str, headers: dict | None = None) -> bytes:
    """One GET with retries on transient failures (Batch 35).

    EDGAR rate-limits the Workers' shared egress IPs (HTTP 429):
    the Scout hit it on company_tickers.json, and the fine-print
    step's 10-Q fetch died on it — 0 items for NVDA despite 12
    real passages waiting (the step's wall was 31s of waiting
    with 32ms CPU, i.e. the fetch failed before any parsing).
    The KPI fetch has the same exposure (it starts with the same
    company_tickers.json call). Retrying here fixes every EDGAR
    caller at once. 4xx other than 429 is permanent (a 404 means
    the document does not exist) and is never retried. The
    pyfetch await also gains a per-attempt timeout: it had none,
    so a hung response could eat a whole step budget."""
    pyfetch = _pyfetch()
    last_exc: Exception | None = None
    for attempt in range(FETCH_RETRY_ATTEMPTS):
        try:
            if pyfetch is not None:
                resp = await asyncio.wait_for(
                    pyfetch(url, headers=headers or {}),
                    timeout=FETCH_ATTEMPT_TIMEOUT_S)
                if resp.status != 200:
                    raise WorkerHTTPError(resp.status, url)
                data = await resp.bytes()
                return bytes(data)
            return await asyncio.to_thread(_sync_fetch_once, url, headers)
        except Exception as e:  # noqa: BLE001 - retried below, re-raised at the end
            last_exc = e
            if not _retryable(e) or attempt == FETCH_RETRY_ATTEMPTS - 1:
                raise
            delay = FETCH_RETRY_DELAYS_S[min(attempt, len(FETCH_RETRY_DELAYS_S) - 1)]
            await asyncio.sleep(delay)
    raise last_exc  # pragma: no cover - the loop always raises or returns


def _retryable(exc: Exception) -> bool:
    """Transient (worth retrying) vs permanent failures."""
    if isinstance(exc, WorkerHTTPError):
        return exc.code in _RETRYABLE_STATUS
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return True
    # Network errors (connection reset, DNS, remote closed) are
    # transient; anything else (a programming error in the
    # caller, a bad URL) is not — but it is safer to retry a
    # transport error once than to drop a briefing on it, so
    # transport-shaped errors retry and the loop still caps at
    # FETCH_RETRY_ATTEMPTS.
    return isinstance(exc, (OSError, ConnectionError))


def _sync_fetch_once(url: str, headers: dict | None) -> bytes:
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
