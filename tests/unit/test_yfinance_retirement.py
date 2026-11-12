"""Batch 64: the yfinance quarterly_history leg is retired.

yfinance is not installed in the Python Workers (pandas is too
heavy), so the Scout's Data notes carried "get_quarterly_history
failed: No module named 'yfinance'" on every deployed run — and
Yahoo's quoteSummary endpoint now demands a crumb, so there is
no lightweight drop-in. The EDGAR overlay already returns the
full 8-quarter series for every metric, so the leg was redundant:
the Scout now builds its facts from SEC EDGAR XBRL alone, and
the async market tool answers from the same EDGAR series.
"""
import asyncio

import pytest

import mesh.async_tools as async_tools
from mesh.scout import collect_evidence
from mesh.scout_async import collect_evidence_async


def _fake(server, tool, args=None):
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
            {"id": "edgar_operating_income_2026-09-30", "metric": "operating_income",
             "value": 40.576, "unit": "USD_B", "period": "2026-09-30",
             "source_tag": "OperatingIncomeLoss", "derived": False, "derivation": "",
             "form": "10-Q", "filed": "2026-10-28"},
            {"id": "edgar_total_revenue_2026-06-30", "metric": "total_revenue",
             "value": 100.0, "unit": "USD_B", "period": "2026-06-30",
             "source_tag": "Revenues", "derived": False, "derivation": "",
             "form": "10-Q", "filed": "2026-07-29"},
        ], "missing": []}
    if (server, tool) == ("market", "get_price_reaction"):
        return {"error": "Nasdaq fetch failed in this test"}
    if (server, tool) == ("estimates_news", "get_consensus_estimates"):
        return {"status": "available", "fiscal_quarter_ending": "Sep/2026",
                "eps_estimate": 2.94, "num_estimates": 14}
    if (server, tool) == ("filings", "get_transcript_excerpt"):
        return {"status": "unavailable"}
    raise AssertionError(f"unexpected tool call: {server}/{tool}")


async def _async_fake(server, tool, args=None):
    return _fake(server, tool, args)


def test_scout_facts_are_edgar_only_no_yfinance_note():
    pack = collect_evidence("GOOGL", _fake)
    assert pack.status == "REPORTED"
    assert pack.quarter_end.isoformat() == "2026-09-30"
    assert all(f.source.publisher == "SEC EDGAR" for f in pack.facts)
    assert not any("yfinance" in m for m in pack.missing)
    assert not any("get_quarterly_history" in m for m in pack.missing)


def test_async_scout_matches_sync_without_history_leg():
    sync_pack = collect_evidence("GOOGL", _fake)
    async_pack = asyncio.run(collect_evidence_async("GOOGL", _async_fake))
    s, a = sync_pack.model_dump(mode="json"), async_pack.model_dump(mode="json")
    s.pop("report_date"); a.pop("report_date")
    for f in s.get("facts", []):
        f.get("source", {}).pop("retrieved_at", None)
    for f in a.get("facts", []):
        f.get("source", {}).pop("retrieved_at", None)
    assert a == s


def test_async_quarterly_history_answers_from_edgar(monkeypatch):
    async def _fake_filing_facts(ticker, report_date=""):
        return {"ticker": "MSFT", "facts": [
            {"metric": "total_revenue", "value": 70.0, "unit": "USD_B", "period": "2026-09-30"},
            {"metric": "operating_income", "value": 30.0, "unit": "USD_B", "period": "2026-09-30"},
            {"metric": "total_revenue", "value": 65.0, "unit": "USD_B", "period": "2026-06-30"},
            {"metric": "gaap_eps", "value": 3.0, "unit": "USD", "period": "2026-09-30"},
        ]}
    monkeypatch.setattr(async_tools, "async_get_filing_facts", _fake_filing_facts)
    out = asyncio.run(async_tools.async_get_quarterly_history("MSFT", quarters=2))
    assert out["source"] == "SEC EDGAR XBRL"
    assert [r["period_end"] for r in out["quarters"]] == ["2026-09-30", "2026-06-30"]
    assert out["quarters"][0]["total_revenue"] == pytest.approx(70.0e9)
    assert out["quarters"][0]["operating_income"] == pytest.approx(30.0e9)
    assert "operating_income" not in out["quarters"][1]  # Q2 row has no opinc fact
