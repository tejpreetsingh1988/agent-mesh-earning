"""Orchestrator Worker — the Cloudflare twin of apps/orchestrator/main.py.

Same pipeline (Scout -> Analyst -> Critic gate -> Writer), but:
- Agent calls are async POSTs to the four agent Workers' public
  workers.dev URLs via mesh/worker_http (pyfetch in-Worker) —
  true agent-to-agent calls, not in-process function calls.
- The endpoint is async and CORS-enabled, so the Cloudflare
  Pages frontend can call it cross-origin from a browser.
- No SSE stream here: the Pages frontend makes one POST and
  waits (a full briefing takes roughly a minute: Scout ~5s,
  Critic re-query ~20s, Writer story up to a minute per model
  attempt). The Docker service keeps its SSE stream.

Agent URLs default to the deployed Workers; override with
SCOUT_URL / ANALYST_URL / CRITIC_URL / WRITER_URL env vars
where the runtime surfaces them. Auth is off (no
AGENT_API_TOKEN set on the Workers), so no auth headers are
sent — auth_headers() returns {} without a token.
"""
import asyncio
import os

from mesh.agent_app import create_app
from mesh.auth import auth_headers
from mesh.orchestrator_async import run_briefing_async
from mesh.worker_http import post_json

URLS = {
    "scout": os.environ.get("SCOUT_URL", "https://mesh-scout-proof.tejpreetsingh1988.workers.dev"),
    "analyst": os.environ.get("ANALYST_URL", "https://mesh-analyst-proof.tejpreetsingh1988.workers.dev"),
    "critic": os.environ.get("CRITIC_URL", "https://mesh-critic-proof.tejpreetsingh1988.workers.dev"),
    "writer": os.environ.get("WRITER_URL", "https://mesh-writer-proof.tejpreetsingh1988.workers.dev"),
}

AGENT_TIMEOUT_S = 300


async def _agent_call(agent: str, payload: dict) -> dict:
    body = await asyncio.wait_for(
        post_json(f"{URLS[agent].rstrip('/')}/tasks/send", payload, headers=auth_headers()),
        timeout=AGENT_TIMEOUT_S)
    if body.get("state") != "completed":
        raise RuntimeError(f"{agent} task failed: {body}")
    return body["result"]


async def _handler(payload: dict) -> dict:
    ticker = payload.get("ticker") or payload.get("params", {}).get("ticker")
    if not ticker:
        raise ValueError("Orchestrator task needs a ticker, e.g. {\"ticker\": \"GOOGL\"}")
    briefing = await run_briefing_async(
        ticker,
        scout_fn=lambda t: _agent_call("scout", {"ticker": t}),
        analyst_fn=lambda pack: _agent_call("analyst", {"evidence_pack": pack}),
        critic_fn=lambda pack, analysis: _agent_call("critic", {"evidence_pack": pack, "analysis": analysis}),
        writer_fn=lambda pack, analysis, trace_id: _agent_call("writer", {"evidence_pack": pack, "analysis": analysis, "trace_id": trace_id}),
    )
    return briefing.model_dump(mode="json")


app = create_app("orchestrator", async_handler=_handler, cors=True)


# TEMPORARY DEBUG PROBE — remove after diagnosing the Orchestrator ->
# Scout 404. It repeats the Scout POST with pyfetch directly (string
# body, not bytes) and also GETs Scout /health, so one call separates
# three hypotheses: bytes body vs string body, POST vs GET, and
# Worker-to-Worker routing vs the app itself.
@app.get("/debug/scout-post")
async def _debug_scout_post():
    import json as _json

    from mesh.worker_http import _pyfetch

    pf = _pyfetch()
    if pf is None:
        return {"probe": "not-in-worker"}
    out = {}
    try:
        resp = await pf("https://mesh-scout-proof.tejpreetsingh1988.workers.dev/tasks/send",
                        method="POST",
                        headers={"Content-Type": "application/json"},
                        body=_json.dumps({"ticker": "GOOGL"}))
        out["post_str"] = {"status": resp.status, "body_snippet": (await resp.text())[:500]}
    except Exception as e:
        out["post_str"] = {"error": str(e)[:300]}
    try:
        resp = await pf("https://mesh-scout-proof.tejpreetsingh1988.workers.dev/health")
        out["get_health"] = {"status": resp.status, "body_snippet": (await resp.text())[:200]}
    except Exception as e:
        out["get_health"] = {"error": str(e)[:300]}
    return out


# Cloudflare Workers entrypoint. In the Worker runtime, `workers` is provided;
# locally it is absent, so the import is guarded and Default stays None there.
try:
    from workers import asgi as _worker_asgi
    Default = _worker_asgi.entrypoint(app)
except ImportError:  # local dev / tests only
    Default = None
