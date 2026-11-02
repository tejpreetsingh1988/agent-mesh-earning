"""Async Scout (Worker v2) parity + worker_http fallback tests.

No live network here: worker_http is exercised against a local
HTTP server in a thread (its to_thread fallback path — the
pyfetch path only exists in a Worker and is proven by the live
deploy, not here), and collect_evidence_async is exercised with
an async fake client whose data mirrors the sync fake in
test_scout_analyst.py, so the async pack must match the sync
pack on every field except timestamps.
"""
import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient

from mesh.agent_app import create_app
from mesh.async_tools import async_direct_call
from mesh.scout import collect_evidence
from mesh.scout_async import collect_evidence_async
from mesh.worker_http import WorkerHTTPError, fetch_bytes, fetch_json, fetch_text


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/data.json":
            body = json.dumps({"hello": "world"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/text":
            body = b"plain text"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()


@pytest.fixture(scope="module")
def _server():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_worker_http_fallback_json_text_and_404(_server):
    assert asyncio.run(fetch_json(f"{_server}/data.json")) == {"hello": "world"}
    assert asyncio.run(fetch_text(f"{_server}/text")) == "plain text"
    assert asyncio.run(fetch_bytes(f"{_server}/text")) == b"plain text"
    with pytest.raises(WorkerHTTPError) as exc:
        asyncio.run(fetch_text(f"{_server}/missing"))
    assert exc.value.code == 404


def _sync_fake(server, tool, args=None):
    args = args or {}
    if (server, tool) == ("filings", "get_company_facts"):
        return {"ticker": "GOOGL", "company_name": "Alphabet Inc."}
    if (server, tool) == ("filings", "get_latest_earnings_filing"):
        return {"ticker": "GOOGL", "filingDate": "2026-10-28",
                "accessionNumber": "0001652044-26-000080",
                "primaryDocument": "goog-20261028.htm"}
    if (server, tool) == ("filings", "list_recent_filings"):
        return {"filings": []}
    if (server, tool) == ("filings", "get_filing_text"):
        return {"excerpt": ""}
    if (server, tool) == ("filings", "get_filing_facts"):
        return {"facts": [
            {"id": "edgar_total_revenue_2026-09-30", "metric": "total_revenue",
             "value": 127.577, "unit": "USD_B", "period": "2026-09-30",
             "source_tag": "Revenues", "derived": False, "derivation": "",
             "form": "10-Q", "filed": "2026-10-28"},
        ], "missing": []}
    if (server, tool) == ("market", "get_quarterly_history"):
        return {"quarters": [
            {"period_end": "2026-09-30", "total_revenue": 127577000000,
             "operating_income": 40576000000},
            {"period_end": "2026-06-30", "total_revenue": 100000000000,
             "operating_income": 30000000000},
        ]}
    if (server, tool) == ("market", "get_price_reaction"):
        return {"error": "no yfinance in this test"}
    if (server, tool) == ("estimates_news", "get_consensus_estimates"):
        return {"status": "available", "fiscal_quarter_ending": "Sep/2026",
                "eps_estimate": 2.94, "num_estimates": 14}
    if (server, tool) == ("filings", "get_transcript_excerpt"):
        return {"status": "unavailable"}
    raise AssertionError(f"unexpected tool call: {server}/{tool}")


async def _async_fake(server, tool, args=None):
    return _sync_fake(server, tool, args)


def _comparable(pack):
    d = pack.model_dump(mode="json")
    d.pop("report_date", None)
    for f in d.get("facts", []):
        f.get("source", {}).pop("retrieved_at", None)
    return d


def test_collect_evidence_async_matches_sync():
    sync_pack = collect_evidence("GOOGL", _sync_fake)
    async_pack = asyncio.run(collect_evidence_async("GOOGL", _async_fake))
    s, a = _comparable(sync_pack), _comparable(async_pack)
    assert a == s
    assert a["status"] == "REPORTED"
    assert a["quarter_end"] == "2026-09-30"
    assert a["quarter_label"] == "Q3 2026"
    pubs = {f["source"]["publisher"] for f in a["facts"]}
    assert "SEC EDGAR" in pubs  # overlay replaced the yfinance 2026-09-30 fact
    assert any("get_price_reaction" in m for m in a["missing"])


def test_collect_evidence_async_first_step_failure():
    async def _failing(server, tool, args=None):
        raise RuntimeError("boom")

    pack = asyncio.run(collect_evidence_async("GOOGL", _failing))
    assert pack.status == "NOT_REPORTED_YET"
    assert pack.facts == []
    assert any("get_company_facts failed" in m for m in pack.missing)


def test_agent_app_async_endpoint_and_sync_regression():
    async def _async_handler(payload):
        return {"ok": True, "ticker": payload.get("ticker")}

    def _sync_handler(payload):
        return {"ok": True, "ticker": payload.get("ticker")}

    async_app = create_app("scout", async_handler=_async_handler)
    res = TestClient(async_app).post("/tasks/send", json={"ticker": "GOOGL"}).json()
    assert res["state"] == "completed"
    assert res["result"] == {"ok": True, "ticker": "GOOGL"}

    sync_app = create_app("analyst", handler=_sync_handler)
    res = TestClient(sync_app).post("/tasks/send", json={"ticker": "GOOGL"}).json()
    assert res["state"] == "completed"
    assert res["result"] == {"ok": True, "ticker": "GOOGL"}


def test_async_direct_call_unknown_tool():
    with pytest.raises(ValueError, match="Unknown MCP tool"):
        asyncio.run(async_direct_call("filings", "no_such_tool", {}))
