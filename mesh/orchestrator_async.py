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
forwards these to the browser as the live log; errors are NOT
emitted here — they propagate to the caller, which turns them
into the stream's error event, so a failed run still ends the
stream cleanly instead of hanging it.
"""
import asyncio
import uuid

from .orchestrator import CriticFailed
from .schemas import Analysis, Briefing, EvidencePack
from .writer import write_briefing


async def _emit(on_event, event: dict):
    if on_event is None:
        return
    result = on_event(event)
    if asyncio.iscoroutine(result):
        await result


async def run_briefing_async(ticker: str, scout_fn, analyst_fn, critic_fn, writer_fn=None,
                             on_event=None) -> Briefing:
    """scout_fn(ticker) -> awaitable EvidencePack dict
    analyst_fn(pack dict) -> awaitable Analysis dict
    critic_fn(pack dict, analysis dict) -> awaitable Critique dict
    writer_fn(pack dict, analysis dict, trace_id) -> awaitable Briefing dict
    (optional; defaults to local write_briefing).
    on_event(event dict) -> optional callback, sync or async,
    called once per pipeline step with the step's outcome."""
    trace_id = str(uuid.uuid4())
    await _emit(on_event, {"event": "scout_started", "ticker": ticker})
    pack_data = await scout_fn(ticker)
    pack = EvidencePack.model_validate(pack_data)
    await _emit(on_event, {"event": "scout_done", "status": pack.status,
                           "facts": len(pack.facts)})
    if pack.status != "REPORTED":
        raise ValueError(f"NOT_REPORTED_YET for {ticker}: {pack.missing}")
    analysis_data = await analyst_fn(pack_data)
    analysis = Analysis.model_validate(analysis_data)
    await _emit(on_event, {"event": "analyst_done",
                           "claims": len(analysis.claims)})

    attempts = 0
    while attempts < 2:
        attempts += 1
        critique_data = await critic_fn(pack_data, analysis_data)
        await _emit(on_event, {"event": "critic_attempt", "attempt": attempts,
                               "verdict": critique_data.get("verdict")})
        if critique_data.get("verdict") == "PASS":
            break
        if attempts >= 2:
            raise CriticFailed(critique_data.get("issues", []))
        analysis_data = await analyst_fn(pack_data)
        analysis = Analysis.model_validate(analysis_data)
        await _emit(on_event, {"event": "analyst_done",
                               "claims": len(analysis.claims)})
    else:
        raise CriticFailed(critique_data.get("issues", []))

    if writer_fn is not None:
        briefing_data = await writer_fn(pack_data, analysis_data, trace_id)
        await _emit(on_event, {"event": "writer_done",
                               "story_model": briefing_data.get("story_model")})
        return Briefing.model_validate(briefing_data)
    briefing = write_briefing(pack, analysis, trace_id)
    await _emit(on_event, {"event": "writer_done",
                           "story_model": briefing.story_model})
    return briefing
