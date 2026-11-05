"""Batch 27 (Phase 1): the briefing carries its transcript excerpt
+ quarter end, and the Orchestrator's _log_transcript helper posts
it best-effort to the log Worker."""
import asyncio
import importlib.util
import pathlib
from datetime import date, datetime

from mesh.schemas import Analysis, EvidencePack
from mesh.writer import write_briefing

REPO = pathlib.Path(__file__).parents[2]


def _pack(transcript):
    return EvidencePack(
        ticker="MSFT", company_name="Microsoft Corp",
        quarter_label="quarter ended 2026-09-30",
        quarter_end=date(2026, 9, 30),
        report_date=datetime(2026, 10, 28, 20, 30),
        status="REPORTED", facts=[], guidance_verbatim=[],
        transcript=transcript)


def _analysis():
    return Analysis(ticker="MSFT", quarter_label="quarter ended 2026-09-30",
                    verdict_draft="Strong quarter.", claims=[],
                    drivers=[], risks_and_watch=[])


def _story():
    return {"story": "x" * 700, "model": "test"}


def test_write_briefing_carries_transcript_excerpt_and_quarter_end():
    pack = _pack({"status": "available",
                  "url": "https://www.fool.com/earnings/call/2026/10/28/microsoft-msft-q3-2026-earnings-call-transcript/",
                  "source": "Motley Fool",
                  "excerpt": "CEO: Cloud grew strongly this quarter."})
    briefing = write_briefing(pack, _analysis(), "trace-test", story_result=_story())
    assert briefing.transcript_excerpt == "CEO: Cloud grew strongly this quarter."
    assert briefing.transcript_url.startswith("https://www.fool.com/")
    assert briefing.quarter_end == "2026-09-30"


def test_write_briefing_without_transcript_has_empty_excerpt():
    pack = _pack({"status": "unavailable", "reason": "no transcript found"})
    briefing = write_briefing(pack, _analysis(), "trace-test", story_result=_story())
    assert briefing.transcript_excerpt == ""
    assert briefing.transcript_url == ""
    assert briefing.quarter_end == "2026-09-30"


def _load_worker_main():
    spec = importlib.util.spec_from_file_location(
        "orch_worker_main_for_test", REPO / "apps" / "orchestrator" / "worker_main.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_log_transcript_posts_and_is_best_effort(monkeypatch):
    mod = _load_worker_main()
    calls = []

    async def fake_post(url, payload, headers=None):
        calls.append((url, payload))
        return {"ok": True}

    monkeypatch.setattr(mod, "post_json", fake_post)
    monkeypatch.setattr(mod, "TRANSCRIPT_LOG_URL", "https://log.example.dev")
    briefing = {"ticker": "MSFT", "quarter_label": "quarter ended 2026-09-30",
                "quarter_end": "2026-09-30",
                "transcript_url": "https://www.fool.com/x",
                "transcript_excerpt": "CEO: Cloud grew."}
    asyncio.run(mod._log_transcript(briefing))
    assert len(calls) == 1
    url, payload = calls[0]
    assert url == "https://log.example.dev/log"
    assert payload["ticker"] == "MSFT"
    assert payload["quarter_end"] == "2026-09-30"
    assert payload["source_type"] == "text"
    # No excerpt -> no call at all.
    asyncio.run(mod._log_transcript({**briefing, "transcript_excerpt": ""}))
    assert len(calls) == 1
    # A failing log call is swallowed, never an exception.
    async def failing_post(url, payload, headers=None):
        raise RuntimeError("log worker down")

    monkeypatch.setattr(mod, "post_json", failing_post)
    asyncio.run(mod._log_transcript(briefing))
