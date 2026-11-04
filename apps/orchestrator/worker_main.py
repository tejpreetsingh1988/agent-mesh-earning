"""Orchestrator Worker — the Cloudflare twin of apps/orchestrator/main.py.

Same pipeline (Scout -> Analyst -> Critic gate -> Writer), but:
- Agent calls are async POSTs to the four agent Workers' public
  workers.dev URLs via mesh/worker_http (pyfetch in-Worker) —
  true agent-to-agent calls, not in-process function calls.
- The endpoint is async and CORS-enabled, so the Cloudflare
  Pages frontend can call it cross-origin from a browser.
- GET /tasks/stream?ticker=X is the live log: it runs the same
  pipeline with an on_event callback and streams one SSE data
  line per step (scout_started, scout_done, analyst_done,
  critic_attempt, writer_done), then a final briefing event
  with the full Briefing JSON, or an error event. POST
  /tasks/send stays exactly as it was, as the fallback.
  OPEN QUESTION, verified live not assumed: whether the Python
  Workers asgi adapter flushes each SSE chunk as it arrives or
  buffers the whole response. If it buffers, the log lines
  arrive all at once at the end — degraded, not broken — and
  the frontend renders them the same way, then the briefing.

Agent URLs default to the deployed Workers; override with
SCOUT_URL / ANALYST_URL / CRITIC_URL / WRITER_URL env vars
where the runtime surfaces them. Auth is off (no
AGENT_API_TOKEN set on the Workers), so no auth headers are
sent — auth_headers() returns {} without a token.
"""
import asyncio
import json
import os

from fastapi.responses import StreamingResponse

from mesh.agent_app import create_app
from mesh.auth import auth_headers
from mesh.orchestrator_async import error_event, run_briefing_async
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


@app.get("/tasks/stream")
async def tasks_stream(ticker: str = ""):
    """SSE live log for one briefing. Same pipeline as POST
    /tasks/send, but each step is streamed as it happens so the
    frontend can show progress instead of a spinner. The queue
    decouples the pipeline task from the response generator:
    the pipeline pushes events, the generator yields them as
    `data: {...}` lines, and a None sentinel ends the stream
    after the final briefing (or error) event. A missing ticker
    is an error event, not a 400, so the frontend's stream
    reader handles every outcome through one code path."""
    ticker = (ticker or "").strip().upper()
    queue: asyncio.Queue = asyncio.Queue()

    async def _on_event(event: dict):
        await queue.put(event)

    async def _run():
        try:
            if not ticker:
                raise ValueError('Orchestrator task needs a ticker, e.g. /tasks/stream?ticker=GOOGL')
            briefing = await run_briefing_async(
                ticker,
                scout_fn=lambda t: _agent_call("scout", {"ticker": t}),
                analyst_fn=lambda pack: _agent_call("analyst", {"evidence_pack": pack}),
                critic_fn=lambda pack, analysis: _agent_call("critic", {"evidence_pack": pack, "analysis": analysis}),
                writer_fn=lambda pack, analysis, trace_id: _agent_call("writer", {"evidence_pack": pack, "analysis": analysis, "trace_id": trace_id}),
                on_event=_on_event,
            )
            await queue.put({"event": "briefing",
                             "briefing": briefing.model_dump(mode="json")})
        except Exception as e:
            await queue.put(error_event(e))
        finally:
            await queue.put(None)

    task = asyncio.create_task(_run())

    async def _generate():
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield f"data: {json.dumps(item)}\n\n"
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(_generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})
