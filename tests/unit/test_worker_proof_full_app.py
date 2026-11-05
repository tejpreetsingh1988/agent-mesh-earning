"""Cloudflare Worker proofs: Critic, Writer, Orchestrator.

Same import-swap trick as test_worker_proof_scout.py (the
analyst/scout proof tests already import modules named `worker`
and `mesh` in this pytest process): each proof is loaded with
its vendored `mesh` on the path, then the repo cache is
restored. No live network: fakes stand in for the async tools
and agent calls; the real Worker deploys are the remaining
proof steps.
"""
import pathlib
import sys

import pytest
from fastapi.testclient import TestClient

from mesh.schemas import Analysis, EvidencePack
from mesh.writer import write_briefing

_ROOT = pathlib.Path(__file__).parents[2]


def _load_proof(name):
    src = _ROOT / "cloudflare-proof" / name / "src"
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
    return proof, src


_CRITIC_PROOF, _CRITIC_SRC = _load_proof("critic")
_WRITER_PROOF, _WRITER_SRC = _load_proof("writer")
_ORCH_PROOF, _ORCH_SRC = _load_proof("orchestrator")


def _pack_dict():
    from datetime import datetime, timezone
    src = {"url": "", "publisher": "SEC EDGAR",
           "retrieved_at": datetime(2026, 10, 28, tzinfo=timezone.utc).isoformat(),
           "excerpt": "test"}
    return {
        "ticker": "GOOGL", "company_name": "Alphabet Inc.",
        "quarter_label": "Q3 2026", "quarter_end": "2026-09-30",
        "report_date": "2026-10-28T00:00:00+00:00", "status": "REPORTED",
        "facts": [
            {"id": "rev_2025-09-30", "metric": "total_revenue", "value": 102.3,
             "unit": "USD_B", "period": "2025-09-30", "source": src},
            {"id": "rev_2026-09-30", "metric": "total_revenue", "value": 127.577,
             "unit": "USD_B", "period": "2026-09-30", "source": src},
            {"id": "opinc_2025-09-30", "metric": "operating_income", "value": 20.0,
             "unit": "USD_B", "period": "2025-09-30", "source": src},
            {"id": "opinc_2026-09-30", "metric": "operating_income", "value": 40.576,
             "unit": "USD_B", "period": "2026-09-30", "source": src},
        ],
        "guidance_verbatim": [], "consensus": None, "price_reaction": None,
        "transcript": {"status": "unavailable"}, "missing": [],
    }


def _analysis_dict():
    return {
        "ticker": "GOOGL", "quarter_label": "Q3 2026",
        "verdict_draft": "A strong operating quarter.",
        "claims": [
            {"text": "Revenue YoY growth (2025-09-30 -> 2026-09-30)", "value": 24.7,
             "derivation": "127.577 vs 102.3", "evidence_ids": ["rev_2025-09-30", "rev_2026-09-30"]},
            {"text": "Operating income YoY growth (2025-09-30 -> 2026-09-30)", "value": 102.9,
             "derivation": "40.576 vs 20.0", "evidence_ids": ["opinc_2025-09-30", "opinc_2026-09-30"]},
            {"text": "Operating margin", "value": 31.8,
             "derivation": "40.576 / 127.577", "evidence_ids": ["rev_2026-09-30", "opinc_2026-09-30"]},
        ],
        "drivers": ["Strength."],
        "beat_miss": [],
        "risks_and_watch": [],
    }


def test_proof_health_and_cards():
    for proof, name, skill in [
        (_CRITIC_PROOF, "critic", "critique"),
        (_WRITER_PROOF, "writer", "write_briefing"),
        (_ORCH_PROOF, "orchestrator", "run_briefing"),
    ]:
        client = TestClient(proof.app)
        assert client.get("/health").json()["agent"] == name
        card = client.get("/.well-known/agent.json").json()
        assert card["name"] == f"earnings-{name}"


def test_vendored_copies_match_repo():
    pairs = [
        (_CRITIC_SRC, ["critic_async.py", "critic.py", "analyst.py", "worker_http.py",
                       "async_tools.py", "agent_app.py"]),
        (_WRITER_SRC, ["story_async.py", "worker_env.py", "writer.py", "llm.py", "worker_http.py", "agent_app.py"]),
        (_ORCH_SRC, ["orchestrator_async.py", "orchestrator.py", "writer.py", "llm.py",
                     "worker_http.py", "agent_app.py"]),
    ]
    for src, names in pairs:
        for name in names:
            assert (src / "mesh" / name).read_text() == (_ROOT / "mesh" / name).read_text()


async def _critic_fake(server, tool, args=None):
    if (server, tool) == ("filings", "get_company_facts"):
        return {"ticker": "GOOGL", "company_name": "Alphabet Inc."}
    if (server, tool) == ("filings", "get_latest_earnings_filing"):
        return {"ticker": "GOOGL", "filingDate": "2026-10-28"}
    if (server, tool) == ("estimates_news", "get_consensus_estimates"):
        return {"status": "unavailable"}
    raise AssertionError(f"unexpected tool call: {server}/{tool}")


def test_proof_critic_pass_with_requery(monkeypatch):
    monkeypatch.setattr(_CRITIC_PROOF, "async_direct_call", _critic_fake)
    res = TestClient(_CRITIC_PROOF.app).post("/tasks/send", json={
        "evidence_pack": _pack_dict(), "analysis": _analysis_dict()}).json()
    assert res["state"] == "completed"
    assert res["result"]["verdict"] == "PASS"
    assert "company_name matches filings-mcp" in res["result"]["rechecked_facts"]


def test_proof_writer_uses_async_story(monkeypatch):
    async def _fake_story(pack, analysis, **kwargs):
        return {"story": "Test story paragraph one.\n\nTest story paragraph two.",
                "model": "test-model", "tokens_in": 5, "tokens_out": 6, "latency_s": 0.1}

    async def _fake_kpis(ticker, quarter_end, ai=None, api_key=""):
        return ([], None, "")

    async def _fake_fp(ticker, quarter_end, label, ai=None, api_key=""):
        return ([], [])

    # Batch 33: the proof no longer calls build_story_async
    # directly — the three steps run concurrently inside
    # run_writer_steps_async, whose names live in the vendored
    # mesh.writer_pipeline module globals. Lock the shape: no
    # sequential awaits may come back.
    # Batch 34: the mode branches call the individual step
    # functions (one Writer invocation per step, each with its
    # own CPU budget) — lock those in too.
    proof_src = (_WRITER_SRC / "worker.py").read_text()
    assert "run_writer_steps_async" in proof_src
    assert "run_story_step_async" in proof_src
    assert "run_kpi_step_async" in proof_src
    assert "run_fineprint_step_async" in proof_src
    assert "await build_story_async" not in proof_src
    assert "await kpis_for_pack_async" not in proof_src
    assert "await fineprint_for_pack_async" not in proof_src
    _pipe_globals = _WRITER_PROOF.run_writer_steps_async.__globals__
    monkeypatch.setitem(_pipe_globals, "build_story_async", _fake_story)
    monkeypatch.setitem(_pipe_globals, "kpis_for_pack_async", _fake_kpis)
    monkeypatch.setitem(_pipe_globals, "fineprint_for_pack_async", _fake_fp)
    res = TestClient(_WRITER_PROOF.app).post("/tasks/send", json={
        "evidence_pack": _pack_dict(), "analysis": _analysis_dict(),
        "trace_id": "trace-test"}).json()
    assert res["state"] == "completed"
    assert res["result"]["story"].startswith("Test story")
    assert res["result"]["story_model"] == "test-model"
    assert res["result"]["trace_id"] == "trace-test"
    # Batch 34: a mode=kpi call returns only the KPI result
    # (proves the transform mapped the mode branch, not the
    # sync urllib call — a missed replace would fetch live).
    async def _fake_kpis_items(ticker, quarter_end, ai=None, api_key=""):
        return ([{"metric": "SSS", "value": "5%"}], {"nodes": []}, "https://sec.gov/991")

    monkeypatch.setitem(_pipe_globals, "kpis_for_pack_async", _fake_kpis_items)
    res = TestClient(_WRITER_PROOF.app).post("/tasks/send", json={
        "mode": "kpi", "evidence_pack": _pack_dict(),
        "analysis": _analysis_dict(), "trace_id": "trace-test"}).json()
    assert res["state"] == "completed"
    assert res["result"] == {"kpi_result": {
        "items": [{"metric": "SSS", "value": "5%"}], "diagram": {"nodes": []},
        "source_url": "https://sec.gov/991"}}


def test_proof_orchestrator_chains_agents(monkeypatch):
    pack_d, analysis_d = _pack_dict(), _analysis_dict()
    briefing_d = write_briefing(
        EvidencePack.model_validate(pack_d), Analysis.model_validate(analysis_d),
        "trace-orch", story_result={"story": "Orchestrated story.", "model": "test",
                                    "tokens_in": None, "tokens_out": None,
                                    "latency_s": None}).model_dump(mode="json")

    async def _fake_agent(agent, payload):
        # Batch 34: the Orchestrator calls the Writer three
        # times in parallel, one mode per call — answer each
        # mode with its own result shape.
        if agent == "writer":
            mode = payload.get("mode")
            if mode == "story":
                return {"story_result": {"story": "Orchestrated story.", "model": "test",
                                         "tokens_in": None, "tokens_out": None,
                                         "latency_s": None}}
            if mode == "kpi":
                return {"kpi_result": {"items": [], "diagram": None, "source_url": ""}}
            if mode == "fineprint":
                return {"fine_print_result": {"items": [], "source_urls": []}}
            return briefing_d
        return {"scout": pack_d, "analyst": analysis_d,
                "critic": {"verdict": "PASS", "issues": [], "rechecked_facts": []}}[agent]

    monkeypatch.setattr(_ORCH_PROOF, "_agent_call", _fake_agent)
    res = TestClient(_ORCH_PROOF.app).post("/tasks/send", json={"ticker": "GOOGL"}).json()
    assert res["state"] == "completed"
    assert res["result"]["ticker"] == "GOOGL"
    assert res["result"]["story"] == "Orchestrated story."


def test_proof_entrypoints_absent_locally():
    assert _CRITIC_PROOF.Default is None
    assert _WRITER_PROOF.Default is None
    assert _ORCH_PROOF.Default is None
