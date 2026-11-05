"""Batch 34: the Writer runs as three mode calls
(story/kpi/fineprint), each its own Worker invocation with its
own CPU budget, and the Orchestrator assembles the Briefing.
A single Writer invocation kept dying at exactly 2,010ms CPU
on GOOGL; the split is what fixes it.

Batch 42: the three mode calls run SEQUENTIALLY (story, then
KPI, then fine print), not in parallel — the parallel calls
contended for the Workers AI free tier, for SEC, and for the
2,000ms CPU budget (dashboard 503s in clusters at the parallel
calls' minutes), so the KPI leg returned empty in full runs
while working alone."""
import asyncio
from datetime import date, datetime, timezone

from agents.writer.main import _handler as _writer_handler
import agents.writer.main as _writer_main
from mesh.orchestrator_async import run_briefing_async
from mesh.schemas import Analysis, EvidencePack


def _pack_dict():
    return {
        "ticker": "GOOGL", "company_name": "Alphabet Inc.",
        "quarter_label": "Q3 2026", "quarter_end": "2026-09-30",
        "report_date": datetime(2026, 10, 28, tzinfo=timezone.utc).isoformat(),
        "status": "REPORTED", "facts": [
            {"id": "edgar_total_revenue_2026-09-30", "metric": "total_revenue",
             "value": 127.577, "unit": "USD_B", "period": "2026-09-30",
             "source": {"url": "", "publisher": "SEC EDGAR",
                        "retrieved_at": datetime(2026, 10, 28, tzinfo=timezone.utc).isoformat(),
                        "excerpt": "SEC EDGAR XBRL, tag Revenues; form 10-Q."}},
        ],
        "missing": [], "transcript": {"status": "unavailable"},
    }


def _analysis_dict():
    return {
        "ticker": "GOOGL", "quarter_label": "Q3 2026",
        "verdict_draft": "Revenue up.",
        "claims": [{"text": "Revenue YoY growth +24.7% ($102.3B -> $127.6B)",
                    "value": 24.7,
                    "derivation": "(127.577 - 102.3) / 102.3 * 100, from facts edgar_total_revenue_2026-09-30 and edgar_total_revenue_2025-09-30.",
                    "evidence_ids": ["edgar_total_revenue_2026-09-30"]}],
        "drivers": ["Search"], "risks_and_watch": [],
    }


async def _fake_scout(ticker):
    return _pack_dict()


async def _fake_analyst(pack):
    return _analysis_dict()


async def _fake_critic(pack, analysis):
    return {"verdict": "PASS", "issues": [], "rechecked_facts": []}


def test_writer_steps_assembles_briefing():
    """The three step results arrive separately; the Briefing
    carries the story, the KPIs and the fine print."""
    events = []

    async def _steps(pack, analysis, trace_id):
        return (
            {"story": "Story from the mode call.", "model": "mode-test",
             "tokens_in": None, "tokens_out": None, "latency_s": None},
            {"items": [{"metric": "SSS", "value": "5%"}], "diagram": {"nodes": []},
             "source_url": "https://sec.gov/991"},
            {"items": [{"section": "Notes", "quote": "q", "why_it_matters": "w"}],
             "source_urls": ["https://sec.gov/10q"]},
        )

    briefing = asyncio.run(run_briefing_async(
        "GOOGL", _fake_scout, _fake_analyst, _fake_critic,
        writer_steps_fn=_steps,
        on_event=lambda e: events.append(e)))
    assert briefing.ticker == "GOOGL"
    assert briefing.story == "Story from the mode call."
    assert briefing.story_model == "mode-test"
    assert briefing.kpis[0]["metric"] == "SSS"
    assert briefing.diagram == {"nodes": []}
    assert briefing.fine_print[0]["section"] == "Notes"
    assert any(e["event"] == "writer_done" and e["story_model"] == "mode-test"
               for e in events)


def test_writer_steps_takes_precedence_over_writer_fn():
    """When both are given, the step path wins (the cloud path);
    the single-call writer_fn is the legacy fallback only."""
    async def _steps(pack, analysis, trace_id):
        return ({"story": "Steps story.", "model": "steps",
                 "tokens_in": None, "tokens_out": None, "latency_s": None},
                {"items": [], "diagram": None, "source_url": ""},
                {"items": [], "source_urls": []})

    async def _writer_fn(pack, analysis, trace_id):
        raise AssertionError("writer_fn must not be called when writer_steps_fn is given")

    briefing = asyncio.run(run_briefing_async(
        "GOOGL", _fake_scout, _fake_analyst, _fake_critic,
        writer_fn=_writer_fn, writer_steps_fn=_steps))
    assert briefing.story == "Steps story."


def test_sync_handler_mode_kpi(monkeypatch):
    """The Docker/sync handler answers a mode=kpi call with only
    the KPI result (no briefing, no story call)."""
    monkeypatch.setattr(_writer_main, "kpis_for_pack_sync",
                        lambda ticker, qend, api_key="": (
                            [{"metric": "SSS", "value": "5%"}], {"nodes": []},
                            "https://sec.gov/991"))
    res = _writer_handler({"mode": "kpi", "evidence_pack": _pack_dict(),
                           "analysis": _analysis_dict(), "trace_id": "t"})
    assert res == {"kpi_result": {"items": [{"metric": "SSS", "value": "5%"}],
                                   "diagram": {"nodes": []},
                                   "source_url": "https://sec.gov/991"}}


def test_sync_handler_mode_fineprint(monkeypatch):
    monkeypatch.setattr(_writer_main, "fineprint_for_pack_sync",
                        lambda ticker, qend, label, api_key="": (
                            [{"section": "Notes", "quote": "q", "why_it_matters": "w"}],
                            ["https://sec.gov/10q"]))
    res = _writer_handler({"mode": "fineprint", "evidence_pack": _pack_dict(),
                           "analysis": _analysis_dict(), "trace_id": "t"})
    assert res == {"fine_print_result": {
        "items": [{"section": "Notes", "quote": "q", "why_it_matters": "w"}],
        "source_urls": ["https://sec.gov/10q"]}}


def test_sync_handler_mode_story(monkeypatch):
    monkeypatch.setattr(_writer_main, "build_story",
                        lambda pack, analysis, api_key="": {
                            "story": "Sync story.", "model": "sync-test",
                            "tokens_in": None, "tokens_out": None, "latency_s": None})
    res = _writer_handler({"mode": "story", "evidence_pack": _pack_dict(),
                           "analysis": _analysis_dict(), "trace_id": "t"})
    assert res == {"story_result": {"story": "Sync story.", "model": "sync-test",
                                    "tokens_in": None, "tokens_out": None,
                                    "latency_s": None}}


def test_sync_handler_no_mode_still_builds_briefing(monkeypatch):
    """No mode = the old full-briefing path, unchanged."""
    monkeypatch.setattr(_writer_main, "kpis_for_pack_sync",
                        lambda ticker, qend, api_key="": ([], None, ""))
    monkeypatch.setattr(_writer_main, "fineprint_for_pack_sync",
                        lambda ticker, qend, label, api_key="": ([], []))
    # write_briefing calls build_story when story_result is None
    # — patch it where mesh.writer imported it.
    import mesh.writer as _w
    monkeypatch.setattr(_w, "build_story",
                        lambda pack, analysis, llm_call=None, api_key=None: {
                            "story": "Full briefing story.", "model": "sync-test",
                            "tokens_in": None, "tokens_out": None, "latency_s": None})
    res = _writer_handler({"evidence_pack": _pack_dict(),
                           "analysis": _analysis_dict(), "trace_id": "t"})
    assert res["story"] == "Full briefing story."
    assert res["ticker"] == "GOOGL"


def test_write_briefing_carries_kpi_debug():
    # Batch 42: the KPI chain's debug dict rides the briefing so a
    # full run's KPI outcome is diagnosable from the stream event.
    from mesh.writer import write_briefing as _wb
    pack = EvidencePack.model_validate(_pack_dict())
    analysis = Analysis.model_validate(_analysis_dict())
    brief = _wb(pack, analysis, "t",
                story_result={"story": "s", "model": "m"},
                kpi_result={"items": [], "diagram": None, "source_url": "",
                            "debug": {"settled_on": "exhausted", "replies": 0,
                                      "errors": [{"leg": "workers_ai", "error": "TimeoutError: "}]}},
                fine_print_result={"items": [], "source_urls": []})
    assert brief.kpi_debug["settled_on"] == "exhausted"
    assert brief.kpi_debug["replies"] == 0


def test_writer_steps_run_sequentially_story_kpi_fineprint(monkeypatch):
    # Batch 42: the Orchestrator's _writer_steps awaits each mode
    # call before starting the next — story, then KPI, then fine
    # print — so the three calls never contend for the model, for
    # SEC, or for the CPU budget at the same instant.
    import importlib.util
    import pathlib
    spec = importlib.util.spec_from_file_location(
        "orch_worker_main_steps_test",
        pathlib.Path(__file__).resolve().parents[2] / "apps" / "orchestrator" / "worker_main.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    order = []

    async def fake_agent_call(agent, payload):
        order.append(payload["mode"])
        if payload["mode"] == "story":
            return {"story_result": {"story": "s", "model": "m"}}
        if payload["mode"] == "kpi":
            return {"kpi_result": {"items": [], "diagram": None, "source_url": "",
                                   "debug": {"settled_on": "items"}}}
        return {"fine_print_result": {"items": [], "source_urls": []}}

    monkeypatch.setattr(mod, "_agent_call", fake_agent_call)
    story, kpi, fp = asyncio.run(mod._writer_steps(_pack_dict(), _analysis_dict(), "t"))
    assert order == ["story", "kpi", "fineprint"]
    assert story["model"] == "m"
    assert kpi["debug"]["settled_on"] == "items"
