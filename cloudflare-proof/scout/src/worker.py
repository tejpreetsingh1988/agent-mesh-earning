"""Scout agent service — Day 3: real EvidencePack via MCP.

Payload: {"ticker": "GOOGL", "quarter": "Q3 2026" (optional)}
Result: EvidencePack JSON. Tools run in-process via mesh/async_tools.py — a Worker has
no sibling MCP services to call over HTTP, and its fetch is
async (pyfetch) because Workers cannot do sync urllib.
"""
from mesh.agent_app import create_app
from mesh.async_tools import async_direct_call
from mesh.scout_async import collect_evidence_async


async def _handler(payload: dict) -> dict:
    ticker = payload.get("ticker") or payload.get("params", {}).get("ticker")
    if not ticker:
        raise ValueError("Scout task needs a ticker, e.g. {\"ticker\": \"GOOGL\"}")
    quarter = payload.get("quarter") or payload.get("params", {}).get("quarter", "")
    pack = await collect_evidence_async(ticker, async_direct_call, quarter=quarter)
    return pack.model_dump(mode="json")


app = create_app("scout", async_handler=_handler)


# Cloudflare Workers entrypoint. In the Worker runtime, `workers` is provided;
# locally it is absent, so the import is guarded and Default stays None there.
try:
    from workers import asgi as _worker_asgi
    Default = _worker_asgi.entrypoint(app)
except ImportError:  # local dev / tests only
    Default = None
