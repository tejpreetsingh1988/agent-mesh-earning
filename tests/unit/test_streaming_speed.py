"""Streaming log events + parallel Scout/Critic fetches.

Streaming: run_briefing_async emits one event per step, and the
Orchestrator Worker's /tasks/stream endpoint forwards them as
SSE lines followed by the full briefing (or an error event).
Speed: Scout Phase A/Phase B and Critic step 7 run their
independent calls concurrently; the tests prove it with an
active-call counter (peak > 1) AND prove the outputs keep
their old order (missing[] notes, rechecked[] entries).
"""
import asyncio
import pathlib
import sys
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from mesh.critic_async import critique_async
from mesh.orchestrator_async import run_briefing_async
from mesh.schemas import Analysis, Claim, EvidencePack, Fact, SourceRef
from mesh.scout_async import collect_evidence_async
from mesh.writer import write_briefing

_ROOT = pathlib.Path(__file__).parents[2]


def _pack_dict():
    return {
        "ticker": "GOOGL", "company_name": "Alphabet Inc.",
        "quarter_label": "Q3 2026", "quarter_end": "2026-09-30",
        "report_date": "2026-10-28T00:00:00+00:00", "status": "REPORTED",
        "facts": [],
    }


def _analysis_dict():
    return {"ticker": "GOOGL", "quarter_label": "Q3 2026",
            "verdict_draft": "draft", "claims": []}


def _briefing_dict():
    return {"ticker": "GOOGL", "quarter_label": "Q3 2026", "verdict": "v",
            "story": "Test story.", "story_model": "test-model",
            "trace_id": "trace-test"}


def test_orchestrator_events_pass():
    asyncio.run(_test_orchestrator_events_pass())


async def _test_orchestrator_events_pass():
    events = []

    async def scout(t):
        return _pack_dict()

    async def analyst(pack):
        return _analysis_dict()

    async def critic(pack, analysis):
        return {"verdict": "PASS", "issues": [], "rechecked_facts": []}

    async def writer(pack, analysis, trace_id):
        return _briefing_dict()

    briefing = await run_briefing_async(
        "GOOGL", scout, analyst, critic, writer, on_event=events.append)
    assert briefing.story_model == "test-model"
    assert [e["event"] for e in events] == [
        "scout_started", "scout_done", "analyst_done",
        "critic_attempt", "writer_done"]
    assert events[0]["ticker"] == "GOOGL"
    assert events[1]["status"] == "REPORTED"
    assert events[3]["attempt"] == 1 and events[3]["verdict"] == "PASS"
    assert events[4]["story_model"] == "test-model"


def test_orchestrator_events_retry_after_critic_fail():
    asyncio.run(_test_orchestrator_events_retry_after_critic_fail())


async def _test_orchestrator_events_retry_after_critic_fail():
    events = []
    calls = {"critic": 0}

    async def scout(t):
        return _pack_dict()

    async def analyst(pack):
        return _analysis_dict()

    async def critic(pack, analysis):
        calls["critic"] += 1
        if calls["critic"] == 1:
            return {"verdict": "FAIL",
                    "issues": [{"severity": "fail", "check": "x", "message": "m"}],
                    "rechecked_facts": []}
        return {"verdict": "PASS", "issues": [], "rechecked_facts": []}

    async def writer(pack, analysis, trace_id):
        return _briefing_dict()

    await run_briefing_async(
        "GOOGL", scout, analyst, critic, writer, on_event=events.append)
    assert [e["event"] for e in events] == [
        "scout_started", "scout_done", "analyst_done",
        "critic_attempt", "analyst_done", "critic_attempt", "writer_done"]
    attempts = [e for e in events if e["event"] == "critic_attempt"]
    assert [(a["attempt"], a["verdict"]) for a in attempts] == [(1, "FAIL"), (2, "PASS")]


def _tracking_fake(responses, tracker):
    async def fake(server, tool, args=None):
        tracker["active"] += 1
        tracker["peak"] = max(tracker["peak"], tracker["active"])
        try:
            await asyncio.sleep(0.02)
            result = responses[(server, tool)]
            if isinstance(result, Exception):
                raise result
            return result
        finally:
            tracker["active"] -= 1
    return fake


def test_scout_phase_b_runs_concurrently_and_keeps_note_order():
    asyncio.run(_test_scout_phase_b_runs_concurrently_and_keeps_note_order())


async def _test_scout_phase_b_runs_concurrently_and_keeps_note_order():
    tracker = {"active": 0, "peak": 0}
    responses = {
        ("filings", "get_company_facts"): {"ticker": "GOOGL", "company_name": "Alphabet Inc."},
        ("filings", "get_latest_earnings_filing"): {
            "ticker": "GOOGL", "filingDate": "2026-10-28",
            "accessionNumber": "0001652044-26-000080", "primaryDocument": "goog-20261028.htm"},
        ("filings", "list_recent_filings"): {"filings": [
            {"accessionNumber": "0001652044-26-000080", "reportDate": "2026-09-30"}]},
        ("filings", "get_filing_text"): {"text": "excerpt"},
        ("market", "get_quarterly_history"): {"quarters": [
            {"period_end": "2026-09-30", "total_revenue": 127577000000,
             "operating_income": 40576000000},
            {"period_end": "2026-06-30", "total_revenue": 100000000000,
             "operating_income": 30000000000}]},
        ("filings", "get_filing_facts"): {"facts": [
            {"id": "edgar_rev_2026-09-30", "metric": "total_revenue", "value": 127.577,
             "unit": "USD_B", "period": "2026-09-30",
             "source_tag": "RevenueFromContractWithCustomerExcludingAssessedTax",
             "form": "10-Q"}]},
        ("market", "get_price_reaction"): RuntimeError("no price feed"),
        ("estimates_news", "get_consensus_estimates"): {
            "status": "forecast_only", "eps_estimate": 2.94, "num_estimates": 14},
        ("filings", "get_transcript_excerpt"): {"status": "unavailable"},
    }
    pack = await collect_evidence_async(
        "GOOGL", _tracking_fake(responses, tracker))
    assert tracker["peak"] >= 3  # six Phase B calls overlap
    assert pack.status == "REPORTED"
    assert str(pack.quarter_end) == "2026-09-30"
    edgar = [f for f in pack.facts if f.source.publisher == "SEC EDGAR"]
    assert len(edgar) == 1 and edgar[0].value == 127.577
    assert pack.missing == [
        "get_price_reaction failed: no price feed",
        "Consensus is forecast-only (EPS forecast $2.94 from 14 estimates, "
        "reported EPS not yet in the consensus source) — no beat/miss can be computed yet.",
    ]


def test_critic_requery_runs_concurrently_and_keeps_recheck_order():
    asyncio.run(_test_critic_requery_runs_concurrently_and_keeps_recheck_order())


async def _test_critic_requery_runs_concurrently_and_keeps_recheck_order():
    tracker = {"active": 0, "peak": 0}
    src = SourceRef(url="", publisher="SEC EDGAR",
                    retrieved_at=datetime(2026, 10, 28, tzinfo=timezone.utc),
                    excerpt="test")
    pack = EvidencePack(
        ticker="GOOGL", company_name="Alphabet Inc.", quarter_label="Q3 2026",
        quarter_end="2026-09-30",
        report_date=datetime(2026, 10, 28, tzinfo=timezone.utc),
        status="REPORTED",
        facts=[Fact(id="rev_2026-09-30", metric="total_revenue", value=127.577,
                    unit="USD_B", period="2026-09-30", source=src),
               Fact(id="opinc_2026-09-30", metric="operating_income", value=40.576,
                    unit="USD_B", period="2026-09-30", source=src)],
        consensus={"status": "available", "eps_estimate": 2.94})
    analysis = Analysis(
        ticker="GOOGL", quarter_label="Q3 2026", verdict_draft="draft",
        claims=[Claim(text="Operating margin (2026-09-30): 31.8% ($40.6B / $127.6B)",
                      value=31.8, derivation="operating income / revenue for 2026-09-30",
                      evidence_ids=["rev_2026-09-30", "opinc_2026-09-30"])])
    responses = {
        ("filings", "get_company_facts"): {"company_name": "Alphabet Inc."},
        ("filings", "get_latest_earnings_filing"): {"filingDate": "2026-10-28"},
        ("estimates_news", "get_consensus_estimates"): {"eps_estimate": 2.94},
    }
    critique = await critique_async(
        pack, analysis, mcp_call=_tracking_fake(responses, tracker))
    assert tracker["peak"] >= 2  # three re-queries overlap
    assert critique.verdict == "PASS"
    assert critique.rechecked_facts == [
        "company_name matches filings-mcp",
        "latest filing date matches filings-mcp",
        "consensus EPS estimate matches estimates-news-mcp re-query",
    ]


def _load_orchestrator_proof():
    src = _ROOT / "cloudflare-proof" / "orchestrator" / "src"
    saved_mesh = {k: v for k, v in sys.modules.items() if k == "mesh" or k.startswith("mesh.")}
    saved_worker = sys.modules.pop("worker", None)
    for k in list(saved_mesh):
        del sys.modules[k]
    sys.path.insert(0, str(src))
    import worker as proof  # noqa: E402
    for k in [k for k in sys.modules if k == "mesh" or k.startswith("mesh.")]:
        del sys.modules[k]
    sys.modules.update(saved_mesh)
    if saved_worker is not None:
        sys.modules["worker"] = saved_worker
    sys.path.remove(str(src))
    return proof


def test_orchestrator_stream_endpoint(monkeypatch):
    proof = _load_orchestrator_proof()
    pack_d, analysis_d = _pack_dict(), _analysis_dict()
    briefing_d = write_briefing(
        EvidencePack.model_validate(pack_d), Analysis.model_validate(analysis_d),
        "trace-orch", story_result={"story": "Orchestrated story.", "model": "test",
                                    "tokens_in": None, "tokens_out": None,
                                    "latency_s": None}).model_dump(mode="json")

    async def _fake_agent(agent, payload):
        return {"scout": pack_d, "analyst": analysis_d,
                "critic": {"verdict": "PASS", "issues": [], "rechecked_facts": []},
                "writer": briefing_d}[agent]

    monkeypatch.setattr(proof, "_agent_call", _fake_agent)
    resp = TestClient(proof.app).get("/tasks/stream?ticker=GOOGL")
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    body = resp.text
    assert body.index('"event": "scout_started"') < body.index('"event": "critic_attempt"')
    assert body.index('"event": "critic_attempt"') < body.index('"event": "briefing"')
    assert "Orchestrated story." in body
