"""Orchestrator task graph — Day 5.

Scout -> Analyst -> Critic -> Writer, with the Critic as a gate:
Writer is only called if Critic returns PASS. If Critic returns
FAIL, the briefing is NOT produced; the error carries the Critic
issues so the user (or a future revision step) can see exactly what
failed. Analyst in v1 is deterministic, so re-running it would
produce the same Analysis — the loop is therefore a gate, not a
blind retry, and the max-2-revision rule from the spec is enforced
by counting Critic attempts and stopping after 2.

run_briefing is pure orchestration: agent callables are injected,
so tests can use direct logic functions and production uses HTTP
agent services (see apps/orchestrator/main.py).
"""
import uuid

from .schemas import Analysis, Briefing, EvidencePack
from .writer import write_briefing


class CriticFailed(Exception):
    def __init__(self, issues):
        self.issues = issues
        super().__init__(f"Critic FAIL: {issues}")


def run_briefing(ticker: str, scout_fn, analyst_fn, critic_fn, writer_fn=None) -> Briefing:
    """scout_fn(ticker) -> EvidencePack dict
    analyst_fn(pack dict) -> Analysis dict
    critic_fn(pack dict, analysis dict) -> Critique dict
    writer_fn(pack dict, analysis dict, trace_id) -> Briefing dict (optional;
    defaults to local write_briefing)."""
    trace_id = str(uuid.uuid4())
    pack_data = scout_fn(ticker)
    pack = EvidencePack.model_validate(pack_data)
    if pack.status != "REPORTED":
        raise ValueError(f"NOT_REPORTED_YET for {ticker}: {pack.missing}")
    analysis_data = analyst_fn(pack_data)
    analysis = Analysis.model_validate(analysis_data)

    attempts = 0
    while attempts < 2:
        attempts += 1
        critique_data = critic_fn(pack_data, analysis_data)
        if critique_data.get("verdict") == "PASS":
            break
        if attempts >= 2:
            raise CriticFailed(critique_data.get("issues", []))
        # Deterministic Analyst would repeat itself, so a second
        # attempt re-runs Analyst once (in case an upstream pack
        # changed) and then re-checks; if it still fails, we stop.
        analysis_data = analyst_fn(pack_data)
        analysis = Analysis.model_validate(analysis_data)
    else:
        raise CriticFailed(critique_data.get("issues", []))

    if writer_fn is not None:
        briefing_data = writer_fn(pack_data, analysis_data, trace_id)
        return Briefing.model_validate(briefing_data)
    return write_briefing(pack, analysis, trace_id)
