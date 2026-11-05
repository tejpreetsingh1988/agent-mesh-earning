"""Batch 33: the Writer's three steps run concurrently under a
per-chain deadline (GOOGL's sequential Writer hit ~299s and the
Orchestrator stream was canceled as "hung" at ~311s)."""
import asyncio
import time
from datetime import date
from types import SimpleNamespace

import mesh.writer_pipeline as wp


def _pack():
    return SimpleNamespace(ticker="MSFT", quarter_end=date(2026, 9, 30),
                           quarter_label="quarter ended 2026-09-30")


def test_steps_run_concurrently(monkeypatch):
    """Three 0.3s steps finish in well under 0.9s — they overlap,
    they do not queue."""
    monkeypatch.setattr(wp, "deterministic_story", lambda p, a: "DET STORY")

    async def fake_story(pack, analysis, api_key="", ai=None):
        await asyncio.sleep(0.3)
        return {"story": "LLM STORY", "model": "llama"}

    async def fake_kpis(ticker, quarter_end, ai=None, api_key="", debug=None):
        await asyncio.sleep(0.3)
        return ([{"metric": "SSS", "value": "5%"}], {"nodes": []}, "https://sec.gov/991")

    async def fake_fp(ticker, quarter_end, label, ai=None, api_key=""):
        await asyncio.sleep(0.3)
        return ([{"section": "MD&A", "quote": "q", "why_it_matters": "w"}], ["https://sec.gov/10q"])

    monkeypatch.setattr(wp, "build_story_async", fake_story)
    monkeypatch.setattr(wp, "kpis_for_pack_async", fake_kpis)
    monkeypatch.setattr(wp, "fineprint_for_pack_async", fake_fp)
    t0 = time.monotonic()
    story, kpi_res, fp_res = asyncio.run(wp.run_writer_steps_async(_pack(), SimpleNamespace()))
    elapsed = time.monotonic() - t0
    assert elapsed < 0.6, f"steps ran sequentially? {elapsed:.2f}s"
    assert story["story"] == "LLM STORY"
    assert kpi_res[0][0]["metric"] == "SSS" and kpi_res[2] == "https://sec.gov/991"
    assert fp_res[0][0]["section"] == "MD&A"


def test_slow_chain_hits_deadline(monkeypatch):
    """A chain slower than the deadline falls back to its hiding
    result while the fast chains pass through."""
    monkeypatch.setattr(wp, "WRITER_CHAIN_TIMEOUT_S", 0.05)
    monkeypatch.setattr(wp, "deterministic_story", lambda p, a: "DET STORY")

    async def slow_story(pack, analysis, api_key="", ai=None):
        await asyncio.sleep(0.5)
        return {"story": "TOO LATE", "model": "llama"}

    async def fast_kpis(ticker, quarter_end, ai=None, api_key="", debug=None):
        return ([{"metric": "SSS", "value": "5%"}], None, "")

    async def fast_fp(ticker, quarter_end, label, ai=None, api_key=""):
        return ([], [])

    monkeypatch.setattr(wp, "build_story_async", slow_story)
    monkeypatch.setattr(wp, "kpis_for_pack_async", fast_kpis)
    monkeypatch.setattr(wp, "fineprint_for_pack_async", fast_fp)
    story, kpi_res, fp_res = asyncio.run(wp.run_writer_steps_async(_pack(), SimpleNamespace()))
    assert story["story"] == "DET STORY"
    assert "timed out" in story["model"]
    assert kpi_res[0][0]["metric"] == "SSS"
    assert fp_res == ([], [])


def test_raising_chain_falls_back(monkeypatch):
    """A chain that raises is contained — the briefing stands."""
    monkeypatch.setattr(wp, "deterministic_story", lambda p, a: "DET STORY")

    async def ok_story(pack, analysis, api_key="", ai=None):
        return {"story": "LLM STORY", "model": "llama"}

    async def boom_kpis(ticker, quarter_end, ai=None, api_key="", debug=None):
        raise RuntimeError("EDGAR down")

    async def ok_fp(ticker, quarter_end, label, ai=None, api_key=""):
        return ([{"section": "Notes", "quote": "q", "why_it_matters": "w"}], [])

    monkeypatch.setattr(wp, "build_story_async", ok_story)
    monkeypatch.setattr(wp, "kpis_for_pack_async", boom_kpis)
    monkeypatch.setattr(wp, "fineprint_for_pack_async", ok_fp)
    story, kpi_res, fp_res = asyncio.run(wp.run_writer_steps_async(_pack(), SimpleNamespace()))
    assert story["story"] == "LLM STORY"
    assert kpi_res == ([], None, "")
    assert fp_res[0][0]["section"] == "Notes"


def test_individual_steps_return_result_dicts(monkeypatch):
    """Batch 34: each step is callable alone and returns its
    result dict (story_result / kpi_result / fine_print_result)
    — the shape the Writer mode calls return."""
    monkeypatch.setattr(wp, "deterministic_story", lambda p, a: "DET STORY")

    async def fake_story(pack, analysis, api_key="", ai=None):
        return {"story": "LLM STORY", "model": "llama"}

    async def fake_kpis(ticker, quarter_end, ai=None, api_key="", debug=None):
        return ([{"metric": "SSS", "value": "5%"}], {"nodes": []}, "https://sec.gov/991")

    async def fake_fp(ticker, quarter_end, label, ai=None, api_key=""):
        return ([{"section": "MD&A", "quote": "q", "why_it_matters": "w"}], ["https://sec.gov/10q"])

    monkeypatch.setattr(wp, "build_story_async", fake_story)
    monkeypatch.setattr(wp, "kpis_for_pack_async", fake_kpis)
    monkeypatch.setattr(wp, "fineprint_for_pack_async", fake_fp)
    pack = _pack()
    assert asyncio.run(wp.run_story_step_async(pack, SimpleNamespace()))["story"] == "LLM STORY"
    kpi = asyncio.run(wp.run_kpi_step_async(pack))
    assert kpi == {"items": [{"metric": "SSS", "value": "5%"}], "diagram": {"nodes": []},
                  "source_url": "https://sec.gov/991", "debug": {"settled_on": "incomplete"}}
    fp = asyncio.run(wp.run_fineprint_step_async(pack))
    assert fp == {"items": [{"section": "MD&A", "quote": "q", "why_it_matters": "w"}],
                  "source_urls": ["https://sec.gov/10q"]}
    # A slow story step still falls back to the deterministic
    # story on its own deadline.
    monkeypatch.setattr(wp, "WRITER_CHAIN_TIMEOUT_S", 0.05)

    async def slow_story(pack, analysis, api_key="", ai=None):
        await asyncio.sleep(0.5)
        return {"story": "TOO LATE", "model": "llama"}

    monkeypatch.setattr(wp, "build_story_async", slow_story)
    timed_out = asyncio.run(wp.run_story_step_async(pack, SimpleNamespace()))
    assert timed_out["story"] == "DET STORY" and "timed out" in timed_out["model"]
