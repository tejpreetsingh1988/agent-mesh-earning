"""Cloudflare Worker proof: the vendored Scout copy must wire the same
collect_evidence to in-process tools, and the direct client must
dispatch every tool Scout uses. No live network here: the fake
mcp_call stands in for direct_call, and the real Worker deploy is
the remaining proof step (can a Worker reach EDGAR/Nasdaq at all
via urllib, and does pywrangler bundle the stack?).

Import isolation note: the analyst proof test already imports a
module named `worker` and a package named `mesh` in this same
pytest process, so this file loads the Scout proof in a swap:
temporarily replace the cached `mesh` tree with the Scout proof's
vendored copy, import its `worker`, then restore the cache and
the path. The proof app object keeps its vendored modules, so
TestClient still exercises the proof code after the restore.
"""
import pathlib
import sys

import pytest
from fastapi.testclient import TestClient

_SCOUT_SRC = pathlib.Path(__file__).parents[2] / "cloudflare-proof" / "scout" / "src"

_saved_mesh = {k: v for k, v in sys.modules.items() if k == "mesh" or k.startswith("mesh.")}
_saved_worker = sys.modules.pop("worker", None)
for _k in list(_saved_mesh):
    del sys.modules[_k]
sys.path.insert(0, str(_SCOUT_SRC))
import worker as proof  # noqa: E402  (path setup above)
from mesh.direct_client import _TOOLS as _PROOF_TOOLS  # noqa: E402  (vendored copy)
for _k in [k for k in sys.modules if k == "mesh" or k.startswith("mesh.")]:
    del sys.modules[_k]
sys.modules.update(_saved_mesh)
if _saved_worker is not None:
    sys.modules["worker"] = _saved_worker
sys.path.remove(str(_SCOUT_SRC))

from mesh.direct_client import _TOOLS, direct_call  # noqa: E402  (repo module)


def _fake_call(server, tool, args=None):
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
        return {"facts": [], "missing": []}
    if (server, tool) == ("market", "get_quarterly_history"):
        return {"quarters": []}
    if (server, tool) == ("market", "get_price_reaction"):
        return {"error": "no yfinance in this test"}
    if (server, tool) == ("estimates_news", "get_consensus_estimates"):
        return {"status": "available", "fiscal_quarter_ending": "Sep/2026",
                "eps_estimate": 2.94, "num_estimates": 14}
    if (server, tool) == ("filings", "get_transcript_excerpt"):
        return {"status": "unavailable"}
    raise AssertionError(f"unexpected tool call: {server}/{tool}")


def test_direct_client_dispatch_covers_scout_tools():
    for server, tool in [
        ("filings", "get_company_facts"), ("filings", "get_latest_earnings_filing"),
        ("filings", "list_recent_filings"), ("filings", "get_filing_text"),
        ("filings", "get_filing_facts"), ("filings", "get_transcript_excerpt"),
        ("market", "get_quarterly_history"), ("market", "get_price_reaction"),
        ("estimates_news", "get_consensus_estimates"),
    ]:
        assert callable(_TOOLS[server][tool])
        assert callable(_PROOF_TOOLS[server][tool])
    with pytest.raises(ValueError, match="Unknown MCP tool"):
        direct_call("filings", "no_such_tool", {})


def test_vendored_copy_matches_repo():
    repo = pathlib.Path(__file__).parents[2] / "mesh" / "direct_client.py"
    copy = _SCOUT_SRC / "mesh" / "direct_client.py"
    assert copy.read_text() == repo.read_text()


def test_proof_scout_health_and_card():
    client = TestClient(proof.app)
    assert client.get("/health").json()["agent"] == "scout"
    card = client.get("/.well-known/agent.json").json()
    assert card["name"] == "earnings-scout"
    assert card["skills"][0]["id"] == "collect_evidence"


def test_proof_scout_uses_direct_call(monkeypatch):
    monkeypatch.setattr(proof, "direct_call", _fake_call)
    res = TestClient(proof.app).post("/tasks/send", json={"ticker": "GOOGL"}).json()
    assert res["state"] == "completed"
    pack = res["result"]
    assert pack["status"] == "REPORTED"
    assert pack["quarter_end"] == "2026-09-30"
    assert pack["quarter_label"] == "Q3 2026"
    assert any("get_price_reaction" in m or "quarterly_history" in m for m in pack["missing"])


def test_worker_entrypoint_absent_locally():
    assert proof.Default is None
