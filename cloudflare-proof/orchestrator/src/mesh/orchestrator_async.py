"""Async Orchestrator — the Worker twin of mesh/orchestrator.py.

run_briefing_async mirrors run_briefing exactly (Scout ->
Analyst -> Critic gate with max 2 attempts -> Writer; Writer
only on Critic PASS; NOT_REPORTED_YET raises before Analyst),
except every agent call is awaited. The sync run_briefing stays
untouched for Docker, the eval harness and the Streamlit path.
This module is imported only by the Cloudflare Orchestrator
Worker proof and by tests.

Progress events: pass on_event to receive one dict per step
(scout_started, scout_done, analyst_done, critic_attempt,
writer_done). The SSE endpoint on the Orchestrator Worker
forwards these to the browser. Each event carries the step's
OUTCOME, not just its name, so the frontend can render each
agent's card the moment it finishes instead of waiting for
the final briefing: scout_done carries the fact list,
analyst_done the claim list, critic_attempt the verdict and
issue list, writer_done the story and its model — plus
duration_ms, how long that agent's call took. The old count
keys (facts, claims) stay exactly as they were, so existing
consumers keep working. Errors are NOT emitted here — they
propagate to the caller, which turns them into the stream's
error event, so a failed run still ends the stream cleanly
instead of hanging it.
"""
import asyncio
import time
import uuid

from .orchestrator import CriticFailed
from .schemas import Analysis, Briefing, EvidencePack
from .writer import write_briefing


def error_event(e: Exception) -> dict:
    """Final stream event for a failed run. A Critic refusal carries
    its verdict and issues in structured form so the frontend can
    render the gate's decision (final FAIL + reasons) instead of
    guessing from a stringified exception. Every other failure
    stays a plain error event, as before."""
    if isinstance(e, CriticFailed):
        return {"event": "error", "error": str(e), "verdict": "FAIL",
                "issues": e.issues}
    return {"event": "error", "error": str(e)}


async def _emit(on_event, event: dict):
    if on_event is None:
        return
    result = on_event(event)
    if asyncio.iscoroutine(result):
        await result


async def run_briefing_async(ticker: str, scout_fn, analyst_fn, critic_fn, writer_fn=None,
                             on_event=None, resume_from=None) -> Briefing:
    """scout_fn(ticker) -> awaitable EvidencePack dict
    analyst_fn(pack dict) -> awaitable Analysis dict
    critic_fn(pack dict, analysis dict) -> awaitable Critique dict
    writer_fn(pack dict, analysis dict, trace_id) -> awaitable Briefing dict
    (optional; defaults to local write_briefing).
    on_event(event dict) -> optional callback, sync or async,
    called once per pipeline step with the step's outcome.
    resume_from (optional dict with "pack"/"analysis"/"critique")
    -> a stage present here is SKIPPED: no agent call, no events
    for it, and the stored output feeds the next stage. A stored
    critique is honoured only when its verdict is PASS (a stored
    FAIL means the Critic loop runs fresh, as if nothing were
    stored). This is Batch 31's fast-forward: a resumed run
    replays the stored events, then runs only the stages the
    original run never finished."""
    trace_id = str(uuid.uuid4())
    resume_from = resume_from or {}
    pack_data = resume_from.get("pack")
    if pack_data is None:
        await _emit(on_event, {"event": "scout_started", "ticker": ticker})
        started = time.monotonic()
        pack_data = await scout_fn(ticker)
        scout_ms = int((time.monotonic() - started) * 1000)
        pack = EvidencePack.model_validate(pack_data)
        await _emit(on_event, {"event": "scout_done", "status": pack.status,
                               "facts": len(pack.facts),
                               "duration_ms": scout_ms,
                               "quarter_label": pack.quarter_label,
                               "company_name": pack.company_name,
                               "transcript_status": (pack.transcript or {}).get("status")
                               if isinstance(pack.transcript, dict) else
                               getattr(pack.transcript, "status", None),
                               "fact_list": pack.model_dump(mode="json")["facts"]})
    else:
        pack = EvidencePack.model_validate(pack_data)
    if pack.status != "REPORTED":
        raise ValueError(f"NOT_REPORTED_YET for {ticker}: {pack.missing}")
    analysis_data = resume_from.get("analysis")
    if analysis_data is None:
        started = time.monotonic()
        analysis_data = await analyst_fn(pack_data)
        analyst_ms = int((time.monotonic() - started) * 1000)
        analysis = Analysis.model_validate(analysis_data)
        await _emit(on_event, {"event": "analyst_done",
                               "claims": len(analysis.claims),
                               "duration_ms": analyst_ms,
                               "claim_list": analysis.model_dump(mode="json")["claims"]})
    else:
        analysis = Analysis.model_validate(analysis_data)

    stored_critique = resume_from.get("critique")
    passed = (isinstance(stored_critique, dict)
              and stored_critique.get("verdict") == "PASS")
    attempts = 0
    while attempts < 2 and not passed:
        attempts += 1
        started = time.monotonic()
        critique_data = await critic_fn(pack_data, analysis_data)
        critic_ms = int((time.monotonic() - started) * 1000)
        await _emit(on_event, {"event": "critic_attempt", "attempt": attempts,
                               "verdict": critique_data.get("verdict"),
                               "duration_ms": critic_ms,
                               "issue_list": critique_data.get("issues", [])})
        if critique_data.get("verdict") == "PASS":
            passed = True
            break
        if attempts >= 2:
            raise CriticFailed(critique_data.get("issues", []))
        started = time.monotonic()
        analysis_data = await analyst_fn(pack_data)
        analyst_ms = int((time.monotonic() - started) * 1000)
        analysis = Analysis.model_validate(analysis_data)
        await _emit(on_event, {"event": "analyst_done",
                               "claims": len(analysis.claims),
                               "duration_ms": analyst_ms,
                               "claim_list": analysis.model_dump(mode="json")["claims"]})
    if not passed:
        raise CriticFailed(critique_data.get("issues", []))

    started = time.monotonic()
    if writer_fn is not None:
        briefing_data = await writer_fn(pack_data, analysis_data, trace_id)
        writer_ms = int((time.monotonic() - started) * 1000)
        await _emit(on_event, {"event": "writer_done",
                               "story_model": briefing_data.get("story_model"),
                               "duration_ms": writer_ms,
                               "story": briefing_data.get("story", "")})
        return Briefing.model_validate(briefing_data)
    briefing = write_briefing(pack, analysis, trace_id)
    writer_ms = int((time.monotonic() - started) * 1000)
    await _emit(on_event, {"event": "writer_done",
                           "story_model": briefing.story_model,
                           "duration_ms": writer_ms,
                           "story": briefing.story})
    return briefing
