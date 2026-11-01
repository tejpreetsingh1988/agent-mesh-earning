"""Thin HTTP client for the Day 2 MCP services.

Scout (and, Day 4, Critic) call MCP tools through this, never by
importing mesh/edgar.py etc. directly. That keeps the agent-to-tool
boundary honest: if the MCP service is down, the agent gets an error
from the tool layer, not a silent local fallback.

In Docker Compose the MCP services are reachable by service name
(filings-mcp, market-mcp, estimates-news-mcp). On a host, localhost
works. Override with FILINGS_MCP_URL / MARKET_MCP_URL /
ESTIMATES_MCP_URL.
"""
import os

import httpx

DEFAULTS = {
    "filings": os.environ.get("FILINGS_MCP_URL", "http://filings-mcp:8101"),
    "market": os.environ.get("MARKET_MCP_URL", "http://market-mcp:8102"),
    "estimates_news": os.environ.get("ESTIMATES_MCP_URL", "http://estimates-news-mcp:8103"),
}


def call_mcp(base_url: str, tool: str, args: dict | None = None) -> dict:
    """POST /tools/call and return the tool's result dict.

    Raises on HTTP errors or on a tool-level error payload, so callers
    must handle failure explicitly (Scout records it in `missing`).
    """
    from .auth import auth_headers
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(
            f"{base_url.rstrip('/')}/tools/call",
            json={"tool": tool, "args": args or {}},
            headers=auth_headers(),
        )
    resp.raise_for_status()
    payload = resp.json()
    if "error" in payload:
        raise RuntimeError(payload["error"])
    return payload.get("result", {})


def make_client(base_urls: dict | None = None):
    """Return a (server, tool, args) -> dict callable, for Scout/Critic.

    Tests pass a fake callable instead; production passes this.

    Transport switch (Day 2b, opt-in): if USE_FASTMCP=1, calls go
    over the real MCP Streamable-HTTP client (mesh/mcp_fast_client,
    one session per call) instead of the legacy /tools/call
    endpoint. Default is legacy, so a missing `mcp` install or
    a protocol issue can never break the working pipeline —
    the flag is the migration, and it is tested by
    tests/unit/test_mcp_fast_client.py against real servers.
    """
    urls = {**DEFAULTS, **(base_urls or {})}

    if os.environ.get("USE_FASTMCP") == "1":
        from .mcp_fast_client import call_fastmcp_sync

        def _fast_call(server: str, tool: str, args: dict | None = None) -> dict:
            return call_fastmcp_sync(urls[server], tool, args or {})

        return _fast_call

    def _call(server: str, tool: str, args: dict | None = None) -> dict:
        return call_mcp(urls[server], tool, args or {})

    return _call


def make_traced_client(tracer, stage: str, base_urls: dict | None = None, inner=None):
    """MCP client that emits trace events and retries once on failure.

    inner: a (server, tool, args) -> dict callable. Defaults to the
    HTTP client above. On failure it emits mcp_failed, then a retry
    event, then tries once more; if that also fails it emits
    mcp_failed again and re-raises, so Scout/Critic can record the
    failure in `missing` instead of crashing the whole briefing.
    """
    import time

    from .trace import MCP_DESCRIPTIONS, mcp_summary

    base = inner or make_client(base_urls)

    def _call(server: str, tool: str, args: dict | None = None) -> dict:
        desc = MCP_DESCRIPTIONS.get(server, server)
        tracer.emit(stage, "mcp_start", "RUNNING",
                    f"Calling {server} — {tool}",
                    f"{desc}. Args: {args or {}}", agent="MCP")
        for attempt in (1, 2):
            try:
                result = base(server, tool, args or {})
                tracer.emit(stage, "mcp_done", "DONE",
                            f"{server} — {tool} returned",
                            mcp_summary(server, tool, result), agent="MCP")
                return result
            except Exception as e:
                tracer.emit(stage, "mcp_failed", "FAIL",
                            f"{server} — {tool} failed (attempt {attempt}/2)",
                            str(e)[:200], agent="MCP")
                if attempt == 1:
                    tracer.emit(stage, "retry", "RETRY",
                                f"Retrying {server} — {tool}",
                                "One retry, then the failure is recorded and the briefing continues without that tool's data.", agent="MCP")
                    time.sleep(0.5)
                    continue
                raise

    return _call
