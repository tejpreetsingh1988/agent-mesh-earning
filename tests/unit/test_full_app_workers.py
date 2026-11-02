"""Full-app Worker pieces: critic_async parity, story_async
fallback + fake-LLM path, orchestrator_async gate, CORS, and
worker_http POST. No live network: POST is exercised against a
local echo server, everything else against fakes.
"""
import asyncio
import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient

from mesh.agent_app import create_app
from mesh.critic import critique
from mesh.critic_async import critique_async
from mesh.llm import deterministic_story
from mesh.orchestrator import CriticFailed
from mesh.orchestrator_async import run_briefing_async
from mesh.schemas import Analysis, EvidencePack, Fact, SourceRef
from mesh.story_async import build_story_async
from mesh.worker_http import WorkerHTTPError, post_json
from mesh.writer import write_briefing


def _src():
    return SourceRef(url="", publisher="SEC EDGAR",
                     retrieved_at=datetime(2026, 10, 28, tzinfo=timezone.utc),
                     excerpt="test")


def _pack_dict():
    return {
        "ticker": "GOOGL", "company_name": "Alphabet Inc.",
        "quarter_label": "Q3 2026", "quarter_end": "2026-09-30",
        "report_date": "2026-10-28T00:00:00+00:00", "status": "REPORTED",
        "facts": [
            {"id": "rev_2025-09-30", "metric": "total_revenue", "value": 102.3,
             "unit": "USD_B", "period": "2025-09-30", "source": _src().model_dump(mode="json")},
            {"id": "rev_2026-09-30", "metric": "total_revenue", "value": 127.577,
             "unit": "USD_B", "period": "2026-09-30", "source": _src().model_dump(mode="json")},
            {"id": "opinc_2025-09-30", "metric": "operating_income", "value": 20.0,
             "unit": "USD_B", "period": "2025-09-30", "source": _src().model_dump(mode="json")},
            {"id": "opinc_2026-09-30", "metric": "operating_income", "value": 40.576,
             "unit": "USD_B", "period": "2026-09-30", "source": _src().model_dump(mode="json")},
        ],
        "guidance_verbatim": [], "consensus": None, "price_reaction": None,
        "transcript": {"status": "unavailable"}, "missing": [],
    }


def _analysis_dict():
    return {
        "ticker": "GOOGL", "quarter_label": "Q3 2026",
        "verdict_draft": ("A strong operating quarter for Alphabet Inc. in Q3 2026, with revenue "
                          "and operating income both growing sharply year over year on broad strength."),
        "claims": [
            {"text": "Revenue YoY growth (2025-09-30 -> 2026-09-30) driven by broad strength across the business",
             "value": 24.7, "derivation": "127.577 vs 102.3", "evidence_ids": ["rev_2025-09-30", "rev_2026-09-30"]},
            {"text": "Operating income YoY growth (2025-09-30 -> 2026-09-30) on operating leverage in the quarter",
             "value": 102.9, "derivation": "40.576 vs 20.0", "evidence_ids": ["opinc_2025-09-30", "opinc_2026-09-30"]},
            {"text": "Operating margin at a healthy level for the quarter, reflecting the stronger operating income",
             "value": 31.8, "derivation": "40.576 / 127.577", "evidence_ids": ["rev_2026-09-30", "opinc_2026-09-30"]},
        ],
        "drivers": ["Cloud and search strength drove revenue growth in the quarter, with operating leverage lifting income faster than sales."],
        "beat_miss": [],
        "risks_and_watch": ["Watch whether the current pace of investment continues to pressure free cash flow in coming quarters."],
    }


def _sync_fake(server, tool, args=None):
    if (server, tool) == ("filings", "get_company_facts"):
        return {"ticker": "GOOGL", "company_name": "Alphabet Inc."}
    if (server, tool) == ("filings", "get_latest_earnings_filing"):
        return {"ticker": "GOOGL", "filingDate": "2026-10-28"}
    if (server, tool) == ("estimates_news", "get_consensus_estimates"):
        return {"status": "unavailable"}
    raise AssertionError(f"unexpected tool call: {server}/{tool}")


async def _async_fake(server, tool, args=None):
    return _sync_fake(server, tool, args)


def test_critic_async_matches_sync():
    pack = EvidencePack.model_validate(_pack_dict())
    analysis = Analysis.model_validate(_analysis_dict())
    sync = critique(pack, analysis, mcp_call=_sync_fake)
    async_ = asyncio.run(critique_async(pack, analysis, mcp_call=_async_fake))
    assert async_.model_dump(mode="json") == sync.model_dump(mode="json")
    assert async_.verdict == "PASS"


def test_critic_async_fail_on_bad_claim():
    pack = EvidencePack.model_validate(_pack_dict())
    bad = _analysis_dict()
    bad["claims"] = [{"text": "Revenue YoY growth (2025-09-30 -> 2026-09-30)",
                      "value": 999.0, "derivation": "wrong", "evidence_ids": ["rev_2026-09-30"]}]
    analysis = Analysis.model_validate(bad)
    res = asyncio.run(critique_async(pack, analysis, mcp_call=_async_fake))
    assert res.verdict == "FAIL"
    assert any(i["severity"] == "fail" for i in res.issues)


def test_story_async_no_key_is_deterministic(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    pack = EvidencePack.model_validate(_pack_dict())
    analysis = Analysis.model_validate(_analysis_dict())
    res = asyncio.run(build_story_async(pack, analysis))
    assert res["model"].startswith("deterministic (no OPENROUTER_API_KEY")
    assert res["story"] == deterministic_story(pack, analysis)


def test_story_async_fake_llm_passes_validation(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    pack = EvidencePack.model_validate(_pack_dict())
    analysis = Analysis.model_validate(_analysis_dict())
    story_text = deterministic_story(pack, analysis)
    assert len(story_text) >= 600  # the fake below must clear the length rule

    async def _fake_llm(model, system, user):
        return {"text": story_text, "model": model,
                "tokens_in": 10, "tokens_out": 20, "latency_s": 0.1}

    res = asyncio.run(build_story_async(pack, analysis, llm_call=_fake_llm))
    assert res["story"] == story_text
    assert res["model"].startswith("nvidia/nemotron-3-ultra-550b-a55b:free")


def test_orchestrator_async_full_pass_and_gate():
    pack_d, analysis_d = _pack_dict(), _analysis_dict()

    async def _scout(ticker):
        return pack_d

    async def _analyst(pack):
        return analysis_d

    async def _critic(pack, analysis):
        return {"verdict": "PASS", "issues": [], "rechecked_facts": []}

    async def _writer(pack, analysis, trace_id):
        return write_briefing(EvidencePack.model_validate(pack), Analysis.model_validate(analysis),
                              trace_id, story_result={"story": "test story", "model": "test",
                                                      "tokens_in": None, "tokens_out": None,
                                                      "latency_s": None}).model_dump(mode="json")

    briefing = asyncio.run(run_briefing_async("GOOGL", _scout, _analyst, _critic, _writer))
    assert briefing.ticker == "GOOGL"
    assert briefing.quarter_label == "Q3 2026"
    assert briefing.story == "test story"

    async def _critic_fail(pack, analysis):
        return {"verdict": "FAIL", "issues": [{"severity": "fail", "check": "x", "message": "bad"}], "rechecked_facts": []}

    with pytest.raises(CriticFailed):
        asyncio.run(run_briefing_async("GOOGL", _scout, _analyst, _critic_fail, _writer))

    async def _scout_unreported(ticker):
        return dict(pack_d, status="NOT_REPORTED_YET", missing=["no filing"])

    with pytest.raises(ValueError, match="NOT_REPORTED_YET"):
        asyncio.run(run_briefing_async("GOOGL", _scout_unreported, _analyst, _critic, _writer))


class _EchoHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        out = json.dumps({"echo": body}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


@pytest.fixture(scope="module")
def _echo_server():
    srv = HTTPServer(("127.0.0.1", 0), _EchoHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_worker_http_post_json_round_trip(_echo_server):
    res = asyncio.run(post_json(f"{_echo_server}/tasks/send", {"ticker": "GOOGL"}))
    assert res == {"echo": {"ticker": "GOOGL"}}


def test_agent_app_cors_headers():
    def _h(payload):
        return {"ok": True}

    cors_app = create_app("scout", handler=_h, cors=True)
    client = TestClient(cors_app)
    opts = client.options("/tasks/send")
    assert opts.status_code == 200
    assert opts.headers.get("access-control-allow-origin") == "*"
    res = client.post("/tasks/send", json={"ticker": "GOOGL"})
    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") == "*"

    plain_app = create_app("scout", handler=_h)
    res = TestClient(plain_app).post("/tasks/send", json={"ticker": "GOOGL"})
    assert res.headers.get("access-control-allow-origin") is None
