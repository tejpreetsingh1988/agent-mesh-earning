"""Async Orchestrator — the Worker twin of mesh/orchestrator.py.

run_briefing_async mirrors run_briefing exactly (Scout ->
Analyst -> Critic gate with max 2 attempts -> Writer; Writer
only on Critic PASS; NOT_REPORTED_YET raises before Analyst),
except every agent call is awaited. The sync run_briefing stays
untouched for Docker, the eval harness and the Streamlit path.
This module is imported only by the Cloudflare Orchestrator
Worker proof and by tests.
"""
import uuid

from .orchestrator import CriticFailed
from .schemas import Analysis, Briefing, EvidencePack
from .writer import write_briefing


async def run_briefing_async(ticker: str, scout_fn, analyst_fn, critic_fn, writer_fn=None) -> Briefing:
    """scout_fn(ticker) -> awaitable EvidencePack dict
    analyst_fn(pack dict) -> awaitable Analysis dict
    critic_fn(pack dict, analysis dict) -> awaitable Critique dict
    writer_fn(pack dict, analysis dict, trace_id) -> awaitable Briefing dict
    (optional; defaults to local write_briefing)."""
    trace_id = str(uuid.uuid4())
    pack_data = await scout_fn(ticker)
    pack = EvidencePack.model_validate(pack_data)
    if pack.status != "REPORTED":
        raise ValueError(f"NOT_REPORTED_YET for {ticker}: {pack.missing}")
    analysis_data = await analyst_fn(pack_data)
    analysis = Analysis.model_validate(analysis_data)

    attempts = 0
    while attempts < 2:
        attempts += 1
        critique_data = await critic_fn(pack_data, analysis_data)
        if critique_data.get("verdict") == "PASS":
            break
        if attempts >= 2:
            raise CriticFailed(critique_data.get("issues", []))
        analysis_data = await analyst_fn(pack_data)
        analysis = Analysis.model_validate(analysis_data)
    else:
        raise CriticFailed(critique_data.get("issues", []))

    if writer_fn is not None:
        briefing_data = await writer_fn(pack_data, analysis_data, trace_id)
        return Briefing.model_validate(briefing_data)
    return write_briefing(pack, analysis, trace_id)
