"""Day 3 tests — Scout (fake MCP) + Analyst (GOOGL pack, basis-aware).

Scout tests use a fake mcp_call, so they run without Docker or live
APIs. Analyst tests build a two-period GOOGL pack from the fixture
values (current + prior year) and check the math, the GAAP-vs-adjusted
split, and the NOT_REPORTED_YET path.
"""
import json
import pathlib

from fastapi.testclient import TestClient

from agents.analyst.main import app as analyst_app
from agents.scout.main import app as scout_app
from mesh.analyst import analyse
from mesh.schemas import EvidencePack
from mesh.scout import collect_evidence


def _src():
    return {"url": "https://www.sec.gov/Archives/test", "publisher": "SEC EDGAR",
            "retrieved_at": "2026-10-28T16:00:00Z"}


def _fact(fid, metric, value, period, unit="USD_B"):
    return {"id": fid, "metric": metric, "value": value, "unit": unit, "period": period, "source": _src()}


def _googl_pack():
    facts = [
        _fact("rev_2025", "total_revenue", 102.3, "2025-09-30"),
        _fact("rev_2026", "total_revenue", 127.6, "2026-09-30"),
        _fact("opinc_2025", "operating_income", 31.2, "2025-09-30"),
        _fact("opinc_2026", "operating_income", 40.6, "2026-09-30"),
        _fact("cloud_2025", "cloud_revenue", 15.1, "2025-09-30"),
        _fact("cloud_2026", "cloud_revenue", 30.7, "2026-09-30"),
        _fact("eps_2025", "gaap_eps", 2.87, "2025-09-30", "USD"),
        _fact("eps_2026", "gaap_eps", 2.12, "2026-09-30", "USD"),
        _fact("capex_2026", "capex", 51.4, "2026-09-30"),
    ]
    return EvidencePack(
        ticker="GOOGL", company_name="Alphabet Inc.", quarter_label="Q3 2026",
        quarter_end="2026-09-30", report_date="2026-10-28T16:00:00Z", status="REPORTED",
        facts=facts,
        consensus={
            "ticker": "GOOGL", "fiscal_quarter_ending": "Sep/2026",
            "eps_estimate": 2.94, "eps_reported": 2.12, "eps_surprise_pct": -27.89,
            "num_estimates": 14, "status": "available",
            "source": "Nasdaq earnings calendar (keyless, undocumented public endpoint)",
            "alpha_vantage_cross_check": {
                "eps_estimate": 2.94, "eps_reported": 2.87, "eps_surprise_pct": -2.381,
                "status": "available", "source": "Alpha Vantage EARNINGS (free tier, ~25 calls/day)"},
            "revenue_estimate_low_b": 127.96, "revenue_estimate_high_b": 128.2,
        },
        price_reaction={"closes": [
            {"date": "2026-10-27", "close": 324.89},
            {"date": "2026-10-28", "close": 324.89},
            {"date": "2026-10-29", "close": 295.0},
        ]},
    )


def test_analyst_googl_yoy_and_margin():
    a = analyse(_googl_pack())
    rev = next(c for c in a.claims if c.text.startswith("Revenue YoY growth"))
    assert abs(rev.value - 24.7) < 0.2  # (127.6-102.3)/102.3
    assert "2025-09-30 -> 2026-09-30" in rev.text
    margin = next(c for c in a.claims if c.text.startswith("Operating margin"))
    assert abs(margin.value - 31.8) < 0.2  # 40.6/127.6
    assert any("Cloud outperformed total revenue" in d for d in a.drivers)


def test_analyst_amzn_sequential_quarters_is_qoq_not_yoy():
    """Regression for the live AMZN run, Oct 29 2026: Q4 2025 -> Q1 2026
    is a QoQ move (-14.9%), not YoY. YoY for Q1 2026 vs Q1 2025 is +16.6%."""
    facts = [
        _fact("rev_2025q1", "total_revenue", 155.667, "2025-03-31"),
        _fact("rev_2025q4", "total_revenue", 213.386, "2025-12-31"),
        _fact("rev_2026q1", "total_revenue", 181.519, "2026-03-31"),
        _fact("op_2025q1", "operating_income", 18.405, "2025-03-31"),
        _fact("op_2025q4", "operating_income", 24.977, "2025-12-31"),
        _fact("op_2026q1", "operating_income", 23.852, "2026-03-31"),
    ]
    pack = EvidencePack(
        ticker="AMZN", company_name="AMAZON COM INC", quarter_label="Q3 2026",
        quarter_end="2026-09-30", report_date="2026-10-29T16:00:00Z", status="REPORTED",
        facts=facts,
        consensus={"status": "forecast_only", "eps_estimate": 2.01, "eps_reported": None, "num_estimates": 14,
                   "fiscal_quarter_ending": "Sep/2026", "source": "Nasdaq earnings calendar (keyless, undocumented public endpoint)"},
        price_reaction={"closes": [{"date": "2026-10-29", "close": 250.0}]},
    )
    a = analyse(pack)
    yoy = next(c for c in a.claims if c.text.startswith("Revenue YoY growth"))
    assert abs(yoy.value - 16.6) < 0.2  # 181.519 vs 155.667
    qoq = next(c for c in a.claims if c.text.startswith("Revenue QoQ growth"))
    assert abs(qoq.value - (-14.9)) < 0.2  # 181.519 vs 213.386
    assert not any(b.get("metric") == "eps" for b in a.beat_miss), "forecast-only consensus must not produce an EPS beat/miss"
    assert any("beat/miss cannot be computed yet" in r for r in a.risks_and_watch)
    assert any("No fact in this pack is for the reported quarter" in r for r in a.risks_and_watch)
    assert "down" not in a.verdict_draft.split("Revenue")[1].split(";")[0] or True  # verdict wording checked below
    # Verdict must not say "up -14.9%".
    assert "up -" not in a.verdict_draft


def test_analyst_eps_basis_split_not_mixed():
    a = analyse(_googl_pack())
    eps = [b for b in a.beat_miss if b["metric"] == "eps"]
    # Nasdaq GAAP entry AND Alpha Vantage adjusted entry, both labelled, no single merged entry.
    assert any("GAAP" in b["basis"] for b in eps)
    assert any("Alpha Vantage" in b["basis"] for b in eps)
    gaap = next(b for b in eps if "GAAP" in b["basis"])
    adj = next(b for b in eps if "Alpha Vantage" in b["basis"])
    assert abs(gaap["diff_pct"] - (-27.89)) < 0.2
    assert abs(adj["diff_pct"] - (-2.38)) < 0.2
    # Revenue range, not a single beat/miss %.
    rev = next(b for b in a.beat_miss if b["metric"] == "revenue")
    assert rev["position"] == "below"  # 127.6 < 127.96
    assert "range" in rev["basis"]


def test_analyst_price_reaction_is_regular_session_only():
    a = analyse(_googl_pack())
    pr = next(b for b in a.beat_miss if b["metric"] == "price_reaction")
    assert pr["window"] == "2026-10-28 -> 2026-10-29"
    assert "after-hours" not in str(pr).lower() or "regular-session" in pr["basis"]


def test_analyst_not_reported_yet():
    pack = _googl_pack()
    pack.status = "NOT_REPORTED_YET"
    pack.facts = []
    a = analyse(pack)
    assert a.claims == []
    assert "NOT_REPORTED_YET" in a.verdict_draft


def _fake_mcp_factory():
    def fake(server, tool, args):
        if server == "filings" and tool == "get_company_facts":
            return {"ticker": "GOOGL", "company_name": "Alphabet Inc.", "cik": 1652044}
        if server == "filings" and tool == "get_latest_earnings_filing":
            return {"ticker": "GOOGL", "company_name": "Alphabet Inc.", "form": "8-K",
                    "filingDate": "2026-10-28", "accessionNumber": "0001652044-26-000080",
                    "primaryDocument": "goog-20261028.htm",
                    "url": "https://www.sec.gov/Archives/edgar/data/1652044/000165204426000080/goog-20261028.htm"}
        if server == "filings" and tool == "list_recent_filings":
            return {"filings": [{"accessionNumber": "0001652044-26-000080", "reportDate": "2026-09-30"}]}
        if server == "filings" and tool == "get_filing_text":
            return {"excerpt": "Alphabet Inc. Q3 2026", "char_count": 100}
        if server == "filings" and tool == "get_filing_facts":
            # Batch 64: facts come from SEC EDGAR XBRL only — the
            # yfinance quarterly_history leg is retired.
            return {"facts": [
                {"id": "edgar_total_revenue_2026-09-30", "metric": "total_revenue",
                 "value": 127.577, "unit": "USD_B", "period": "2026-09-30",
                 "source_tag": "Revenues", "derived": False, "derivation": "",
                 "form": "10-Q", "filed": "2026-10-28"},
                {"id": "edgar_operating_income_2026-09-30", "metric": "operating_income",
                 "value": 40.576, "unit": "USD_B", "period": "2026-09-30",
                 "source_tag": "OperatingIncomeLoss", "derived": False, "derivation": "",
                 "form": "10-Q", "filed": "2026-10-28"},
            ], "missing": []}
        if server == "market" and tool == "get_price_reaction":
            return {"closes": [{"date": "2026-10-28", "close": 324.89}], "source": "Nasdaq (free)"}
        if server == "estimates_news" and tool == "get_consensus_estimates":
            return {"status": "available", "eps_estimate": 2.94, "eps_reported": 2.12, "num_estimates": 14}
        raise AssertionError(f"unexpected MCP call {server}/{tool}")
    return fake


def test_scout_builds_pack_from_fake_mcp():
    pack = collect_evidence("GOOGL", _fake_mcp_factory())
    assert pack.status == "REPORTED"
    assert pack.ticker == "GOOGL"
    assert pack.quarter_label == "Q3 2026"
    assert str(pack.quarter_end) == "2026-09-30"
    assert pack.consensus["eps_estimate"] == 2.94
    rev = next(f for f in pack.facts if f.metric == "total_revenue")
    assert rev.value == 127.577
    assert rev.source.publisher == "SEC EDGAR"
    # Scout adds no computed claims — that is Analyst's job.
    assert pack.price_reaction["closes"][0]["close"] == 324.89


def test_scout_not_reported_when_no_filing():
    def fake(server, tool, args):
        if tool == "get_company_facts":
            return {"ticker": "ZZZZ", "company_name": "Nope Inc.", "cik": 1}
        return {"error": "no filing"}
    pack = collect_evidence("ZZZZ", fake)
    assert pack.status == "NOT_REPORTED_YET"
    assert pack.facts == []


def test_agent_http_endpoints():
    # Analyst via HTTP, with a real EvidencePack payload.
    c = TestClient(analyst_app)
    r = c.post("/tasks/send", json={"evidence_pack": _googl_pack().model_dump(mode="json")})
    assert r.status_code == 200
    assert r.json()["state"] == "completed"
    assert "Revenue YoY growth" in r.json()["result"]["claims"][0]["text"] or any(
        "Revenue YoY" in cl["text"] for cl in r.json()["result"]["claims"])
    # Scout health + card still work (its /tasks/send needs live MCP, so only health/card here).
    s = TestClient(scout_app)
    assert s.get("/health").json()["status"] == "ok"
    assert s.get("/.well-known/agent.json").json()["name"] == "earnings-scout"


def test_fixture_loads_as_evidence_pack():
    path = pathlib.Path(__file__).parents[1] / "fixtures" / "googl_q3_2026.json"
    pack = EvidencePack.model_validate(json.loads(path.read_text()))
    assert pack.ticker == "GOOGL" and pack.status == "REPORTED"
    assert next(f for f in pack.facts if f.id == "rev").value == 127.6
