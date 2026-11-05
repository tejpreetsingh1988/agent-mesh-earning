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
import uuid

from fastapi.responses import JSONResponse, StreamingResponse

from mesh.agent_app import create_app
from mesh.auth import auth_headers
from mesh.filings import fetch_recent_filings_async
from mesh.history import history_for_ticker
from mesh.orchestrator_async import error_event, run_briefing_async
from mesh.ownership import fetch_ownership_async
from mesh.worker_http import fetch_json, post_json

URLS = {
    "scout": os.environ.get("SCOUT_URL", "https://mesh-scout-proof.tejpreetsingh1988.workers.dev"),
    "analyst": os.environ.get("ANALYST_URL", "https://mesh-analyst-proof.tejpreetsingh1988.workers.dev"),
    "critic": os.environ.get("CRITIC_URL", "https://mesh-critic-proof.tejpreetsingh1988.workers.dev"),
    "writer": os.environ.get("WRITER_URL", "https://mesh-writer-proof.tejpreetsingh1988.workers.dev"),
}

AGENT_TIMEOUT_S = 300

TRANSCRIPT_LOG_URL = os.environ.get(
    "TRANSCRIPT_LOG_URL",
    "https://mesh-transcript-log-proof.tejpreetsingh1988.workers.dev")

STREAM_LOG_URL = os.environ.get(
    "STREAM_LOG_URL",
    "https://mesh-stream-log-proof.tejpreetsingh1988.workers.dev")


async def _log_stream_event(run_id: str, seq: int, event: dict) -> None:
    """Batch 31: append one stream event to the run's event log.
    Best-effort — a failed POST never breaks the stream; it only
    means a later resume replays fewer steps. The event is logged
    BEFORE it is queued (see _on_event), so a disconnect that
    cancels the pipeline task cannot lose an event the client
    already saw: the log is the resume's source of truth."""
    try:
        await asyncio.wait_for(
            post_json(f"{STREAM_LOG_URL.rstrip('/')}/event", {
                "run_id": run_id, "seq": seq, "event": event,
            }, headers=auth_headers()),
            timeout=2)
    except Exception:
        pass


async def _save_checkpoint(run_id: str, ticker: str, quarter: str,
                           stage: str, **fields) -> None:
    """Batch 31: upsert the run's stage checkpoint. Awaited (unlike
    event logs) because the checkpoint is what a resume
    fast-forwards on — a stage is only 'done' once its output is
    stored. Failures are swallowed: the run continues, it is
    just not resumable past that stage."""
    body = {"run_id": run_id, "ticker": ticker, "quarter": quarter,
            "stage": stage}
    body.update(fields)
    try:
        await asyncio.wait_for(
            post_json(f"{STREAM_LOG_URL.rstrip('/')}/checkpoint", body,
                      headers=auth_headers()),
            timeout=5)
    except Exception:
        pass


async def _fetch_resume(run_id: str) -> dict | None:
    """Batch 31: GET a stored run + its events from the stream-log
    Worker. None on any failure (unknown run, log Worker down):
    the caller turns None into an unknown_run error event, and
    the frontend falls back to a fresh run — a missing log never
    breaks the stream path."""
    try:
        body = await asyncio.wait_for(
            fetch_json(f"{STREAM_LOG_URL.rstrip('/')}/resume?run_id={run_id}"),
            timeout=5)
        if isinstance(body, dict) and body.get("run"):
            return body
    except Exception:
        pass
    return None


async def _log_transcript(briefing: dict) -> None:
    """Phase 1 of the transcript archive (Batch 27): POST the
    Scout's excerpt to the transcript-log Worker after a briefing
    completes. Best-effort and never blocking — any failure is
    swallowed, and a briefing without a transcript (no excerpt
    or no URL) simply isn't logged. The log Worker dedupes on
    (ticker, quarter_end, source_url), so a Refresh re-run
    doesn't create a second row."""
    excerpt = (briefing or {}).get("transcript_excerpt") or ""
    url = (briefing or {}).get("transcript_url") or ""
    if not excerpt or not url:
        return
    try:
        await asyncio.wait_for(
            post_json(f"{TRANSCRIPT_LOG_URL.rstrip('/')}/log", {
                "ticker": briefing.get("ticker", ""),
                "quarter_label": briefing.get("quarter_label", ""),
                "quarter_end": briefing.get("quarter_end", ""),
                "source_url": url, "excerpt": excerpt,
                "source_type": "text",
            }, headers=auth_headers()),
            timeout=8)
    except Exception:
        pass


async def _agent_call(agent: str, payload: dict) -> dict:
    body = await asyncio.wait_for(
        post_json(f"{URLS[agent].rstrip('/')}/tasks/send", payload, headers=auth_headers()),
        timeout=AGENT_TIMEOUT_S)
    if body.get("state") != "completed":
        raise RuntimeError(f"{agent} task failed: {body}")
    return body["result"]


async def _writer_steps(pack, analysis, trace_id):
    """Batch 42: the Writer's three steps as three SEQUENTIAL
    invocations of the Writer Worker, one per mode, one after
    the other — story, then KPI, then fine print. Batch 34 ran
    them in parallel (asyncio.gather) so each got its own
    2,000ms CPU budget, and a single invocation kept dying at
    exactly 2,010ms CPU on GOOGL. But the parallel calls proved
    worse in practice: the KPI leg works alone (12 items, live,
    Batch 41) yet returns empty in full runs, and the dashboard
    shows the Writer hitting the CPU limit in clusters
    ("Worker exceeded CPU time limit", 503, plus cascade resets
    of sibling requests) at the same minutes the parallel mode
    calls fire — three simultaneous Python isolates paying
    cold-start/import CPU at once, plus three concurrent
    Workers AI calls on one free-tier account and a doubled
    SEC fetch burst (the 99.1 fetched twice). Sequential calls
    warm one isolate and reuse it, and the three steps no
    longer contend for the model or for SEC. Cost: wall-clock
    is the sum (~40s story + ~64s KPI + ~21s fine print,
    inside the 300s agent timeout and the ~300s stream limit).
    The story call raises on failure — a briefing needs a
    story; the KPI and fine-print calls fall back to their
    hiding results (the section hides). The KPI call is retried
    once when it returns empty on exhaustion (Batch 43) —
    Workers AI's 60s timeout on this prompt is load variance,
    and a second attempt gets a fresh queue position. Returns
    (story_result, kpi_result, fine_print_result) for
    run_briefing_async to assemble into the Briefing."""
    async def _step(mode, key, fallback=None):
        try:
            res = await _agent_call("writer", {"mode": mode, "evidence_pack": pack,
                                               "analysis": analysis, "trace_id": trace_id})
            return res[key]
        except Exception:
            if fallback is None:
                raise
            return fallback
    story = await _step("story", "story_result")
    kpi = await _step("kpi", "kpi_result", {"items": [], "diagram": None, "source_url": ""})
    if not kpi.get("items"):
        # Batch 43: retry the KPI call ONCE on exhaustion. The
        # direct call proved Workers AI answers this prompt in
        # ~34s when the queue is quiet and times out at 60s when
        # it is busy (same prompt, same window, 08:35 vs 09:57
        # MST) — a second attempt gets a fresh queue position,
        # and the gateway/OpenRouter legs are rate-limited for
        # hours, so there is no other safety net. Retry only
        # when no model ever replied (settled_on "exhausted")
        # or the mode call itself failed (no debug at all) — a
        # clean empty settle means two models agreed the release
        # has no operating KPIs, and retrying that is waste.
        # Cost: up to ~65s extra on the Writer phase when the
        # first attempt fails (phase ~230s, run ~245s, inside
        # the 300s stream gap limit).
        dbg = kpi.get("debug") or {}
        if dbg.get("settled_on") in (None, "exhausted"):
            retry = await _step("kpi", "kpi_result", {"items": [], "diagram": None, "source_url": ""})
            if retry.get("items") or retry.get("debug"):
                kpi = retry
    fp = await _step("fineprint", "fine_print_result", {"items": [], "source_urls": []})
    return story, kpi, fp


def _scout_payload(ticker: str, quarter: str = "") -> dict:
    """Scout agent payload. A requested quarter ("Q2 2026", or a
    fiscal label like "quarter ended 2026-07-26") rides
    along; empty means the most recent reported quarter."""
    payload = {"ticker": ticker}
    if quarter:
        payload["quarter"] = quarter
    return payload


async def _handler(payload: dict) -> dict:
    ticker = payload.get("ticker") or payload.get("params", {}).get("ticker")
    quarter = payload.get("quarter") or payload.get("params", {}).get("quarter", "")
    if not ticker:
        raise ValueError("Orchestrator task needs a ticker, e.g. {\"ticker\": \"GOOGL\"}")
    briefing = await run_briefing_async(
        ticker,
        scout_fn=lambda t: _agent_call("scout", _scout_payload(t, quarter)),
        analyst_fn=lambda pack: _agent_call("analyst", {"evidence_pack": pack}),
        critic_fn=lambda pack, analysis: _agent_call("critic", {"evidence_pack": pack, "analysis": analysis}),
        writer_steps_fn=_writer_steps,
    )
    dumped = briefing.model_dump(mode="json")
    await _log_transcript(dumped)
    return dumped


app = create_app("orchestrator", async_handler=_handler, cors=True)


@app.get("/ownership")
async def ownership(ticker: str = ""):
    """Company-level trading activity (Batch 24): Nasdaq insider
    trades + institutional holdings, fetched Worker-side because
    Nasdaq sends no CORS headers for browser fetches. Each card
    is null on failure so the frontend hides it. Veridion
    politician disclosures are NOT fetched here — the browser
    fetches those directly (the www host allows CORS, so the
    request counts against the visitor's own IP, not the
    Worker's shared egress IPs, against the free 60/hour tier).
    No auth: the data is public, and the ticker is strictly
    validated inside fetch_ownership_async."""
    try:
        return await fetch_ownership_async(ticker)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


@app.get("/filings")
async def filings(ticker: str = ""):
    """Recent filings card (Feature 12): newest 1x 10-K, 3x 10-Q,
    5x 8-K from the SEC submissions feed — metadata + links only,
    computed in mesh/filings.py. A failed fetch returns an error
    payload and the frontend hides the card."""
    return await fetch_recent_filings_async(ticker)


@app.get("/history")
async def history(ticker: str = "", metric: str = "total_revenue"):
    """Long-history charts (Batch 26): up to 40 quarters of one
    XBRL series + total-return vs-chart data, computed in
    mesh/history.py. Data failures degrade to empty/null parts
    in the payload; only a bad ticker or metric is a 400."""
    try:
        return await history_for_ticker(ticker, metric)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


@app.get("/tasks/stream")
async def tasks_stream(ticker: str = "", quarter: str = "", resume_run_id: str = ""):
    """SSE live log for one briefing. Same pipeline as POST
    /tasks/send, but each step is streamed as it happens so the
    frontend can show progress instead of a spinner. The queue
    decouples the pipeline task from the response generator:
    the pipeline pushes events, the generator yields them as
    `data: {...}` lines, and a None sentinel ends the stream
    after the final briefing (or error) event. A missing ticker
    is an error event, not a 400, so the frontend's stream
    reader handles every outcome through one code path.

    Batch 31 — resume: every run gets a run_id (first event,
    run_started) and every event + stage checkpoint is stored
    in the stream-log Worker. When the connection breaks, the
    generator's finally cancels the pipeline task — the run
    DIES, it does not keep completing server-side — but its
    checkpoint survives. A later request with
    ?resume_run_id=<id> replays the stored events, then runs
    only the unfinished stages (run_briefing_async resume_from),
    under the SAME run_id, so a second break is resumable too.
    An unknown run_id is a single unknown_run error event; the
    frontend falls back to a fresh run. A run whose checkpoint
    says "done" replays straight to its briefing with no
    pipeline run at all."""
    ticker = (ticker or "").strip().upper()
    quarter = (quarter or "").strip()
    resume_run_id = (resume_run_id or "").strip()
    resume_data = None
    if resume_run_id:
        resume_data = await _fetch_resume(resume_run_id)
        if resume_data is None:
            async def _gen_unknown():
                yield ("data: " + json.dumps(
                    {"event": "error", "code": "unknown_run",
                     "error": "Unknown run_id; start a fresh run."}) + "\n\n")
            return StreamingResponse(_gen_unknown(), media_type="text/event-stream",
                                     headers={"Cache-Control": "no-cache",
                                              "X-Accel-Buffering": "no"})
        run = resume_data.get("run") or {}
        ticker = (run.get("ticker") or ticker).upper()
        quarter = run.get("quarter") or ""
    run_id = resume_run_id or str(uuid.uuid4())
    # New events continue after the highest stored seq, so the
    # log's (run_id, seq) primary key never collides on resume.
    seq = [0]
    for stored in (resume_data or {}).get("events") or []:
        try:
            seq[0] = max(seq[0], int(stored.get("seq") or 0))
        except (TypeError, ValueError):
            pass
    queue: asyncio.Queue = asyncio.Queue()

    async def _on_event(event: dict):
        # Log first, then queue: a disconnect that cancels this
        # task mid-log loses nothing the client saw, and the
        # logged event is there for the resume's replay.
        seq[0] += 1
        await _log_stream_event(run_id, seq[0], event)
        await queue.put(event)

    async def _scout(t):
        pack = await _agent_call("scout", _scout_payload(t, quarter))
        await _save_checkpoint(run_id, ticker, quarter, "scout", pack=pack)
        return pack

    async def _analyst(pack):
        analysis = await _agent_call("analyst", {"evidence_pack": pack})
        await _save_checkpoint(run_id, ticker, quarter, "analyst", analysis=analysis)
        return analysis

    async def _critic(pack, analysis):
        critique = await _agent_call("critic", {"evidence_pack": pack, "analysis": analysis})
        # Only a PASS checkpoints: a FAIL leaves the stage at
        # "analyst", so a resume re-runs the Critic loop fresh.
        if critique.get("verdict") == "PASS":
            await _save_checkpoint(run_id, ticker, quarter, "critic", critique=critique)
        return critique

    async def _run():
        try:
            if resume_data is not None:
                for stored in resume_data.get("events") or []:
                    ev = stored.get("event")
                    if isinstance(ev, dict):
                        await queue.put(ev)
                run = resume_data.get("run") or {}
                if (run.get("stage") or "") == "done" and run.get("briefing"):
                    await queue.put({"event": "briefing", "briefing": run["briefing"]})
                    return
                resume_from = {k: run[k] for k in ("pack", "analysis", "critique")
                               if run.get(k)}
            else:
                resume_from = None
            if not ticker:
                raise ValueError('Orchestrator task needs a ticker, e.g. /tasks/stream?ticker=GOOGL')
            if resume_from is None:
                # The "started" checkpoint creates the run row, so
                # even a break during Scout leaves a resumable run
                # (replay only, full pipeline — nothing was stored
                # to fast-forward past yet).
                await _save_checkpoint(run_id, ticker, quarter, "started")
                await _on_event({"event": "run_started", "run_id": run_id})
            briefing = await run_briefing_async(
                ticker,
                scout_fn=_scout,
                analyst_fn=_analyst,
                critic_fn=_critic,
                writer_steps_fn=_writer_steps,
                on_event=_on_event,
                resume_from=resume_from,
            )
            dumped = briefing.model_dump(mode="json")
            # Batch 34: the "done" checkpoint used to be saved
            # inside the old _writer fn; the step-split Writer
            # assembles the Briefing in run_briefing_async, so
            # the checkpoint is saved here, on its return.
            await _save_checkpoint(run_id, ticker, quarter, "done", briefing=dumped)
            await queue.put({"event": "briefing", "briefing": dumped})
            await _log_transcript(dumped)
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


# Cloudflare Workers entrypoint. In the Worker runtime, `workers` is provided;
# locally it is absent, so the import is guarded and Default stays None there.
try:
    from workers import asgi as _worker_asgi
    Default = _worker_asgi.entrypoint(app)
except ImportError:  # local dev / tests only
    Default = None
