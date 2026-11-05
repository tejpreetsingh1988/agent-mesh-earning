"""Batch 26: history math + /history payload assembly with fake
fetchers. No live EDGAR/Nasdaq calls here."""
import asyncio
from datetime import date

import mesh.history as hist


def test_rebase_and_changes():
    pts = [{"period_end": "2024-03-31", "value": 100.0},
           {"period_end": "2024-06-30", "value": 110.0},
           {"period_end": "2024-09-30", "value": 121.0}]
    out = hist.rebase(pts)
    assert [round(p["value_pct"], 2) for p in out] == [0.0, 10.0, 21.0]
    assert abs(hist.total_change_pct(100.0, 121.0) - 21.0) < 1e-9
    assert abs(hist.cagr_pct(100.0, 200.0, date(2024, 1, 1), date(2025, 1, 1)) - 100.0) < 1.0
    assert hist.cagr_pct(0, 200.0, date(2024, 1, 1), date(2025, 1, 1)) is None
    assert hist.rebase([{"period_end": "2024-03-31", "value": 0}]) == []


def test_build_total_return_accepts_nasdaq_us_dates():
    # Batch 28 flip finding: real Nasdaq rows carry MM/DD/YYYY
    # dates, and the old ISO-only _parse_date dropped every one —
    # the vs-chart would have silently hidden on real data.
    closes = [{"date": "10/28/2026", "close": "$324.89"},
              {"date": "10/29/2026", "close": "$283.82"}]
    out = hist.build_total_return(closes, [])
    assert [r["date"] for r in out] == ["2026-10-28", "2026-10-29"]
    assert out[0]["index"] == 1.0
    assert abs(out[1]["index"] - 283.82 / 324.89) < 1e-9


def test_build_total_return_dividend_and_future_ignored():
    closes = [{"date": "2024-06-28", "close": "$100"},
              {"date": "2024-06-30", "close": "$102"},
              {"date": "2024-07-01", "close": "$101"}]
    divs = [{"exOrEffDate": "2024-06-30", "amount": "$1", "type": "Cash"},
            {"exOrEffDate": "2025-01-01", "amount": "$5", "type": "Cash"}]
    out = hist.build_total_return(closes, divs)
    assert [r["index"] for r in out][0] == 1.0
    assert abs(out[1]["index"] - 1.03) < 1e-9  # (102+1)/100
    assert abs(out[2]["index"] - 1.03 * 101 / 102) < 1e-9  # future div ignored


def test_sample_and_read_line():
    tr = [{"date": "2024-06-28", "index": 1.0},
          {"date": "2024-06-30", "index": 1.01},
          {"date": "2024-09-30", "index": 1.11},
          {"date": "2024-12-31", "index": 1.06},
          {"date": "2025-03-31", "index": 1.21}]
    sampled = hist.sample_total_return(tr, ["2024-06-30", "2024-09-30", "2025-03-31", "2025-06-30"])
    assert [s["value"] for s in sampled] == [1.01, 1.11, 1.21, 1.21]  # last repeats: last close on/before
    pts = [{"period_end": f"2024-{m:02d}-30", "value": v}
           for m, v in [(3, 10), (6, 12), (9, 11), (12, 15), (3, 14)]]
    # Fix the last end (March 2025, not 2024) for realism; read_line only uses order.
    pts[-1]["period_end"] = "2025-03-31"
    rl = hist.read_line(pts)
    assert rl["peak_value"] == 15 and rl["peak_end"] == "2024-12-30"
    assert abs(rl["current_vs_peak_pct"] - (14 / 15 - 1) * 100) < 0.01
    assert rl["longest_rise_quarters"] == 2 and rl["longest_decline_quarters"] == 2
    assert rl["biggest_jump"]["pct"] == (15 / 11 - 1) * 100
    assert hist.read_line(pts[:1]) is None


def test_headcount_from_companyfacts():
    cf = {"facts": {"dei": {"EntityNumberOfEmployees": {"units": {"pure": [
        {"end": "2024-06-30", "val": 100000, "fy": 2024, "form": "10-K"},
        {"end": "2025-06-30", "val": 110000, "fy": 2025, "form": "10-K"}]}}}}}
    out = hist.headcount_from_companyfacts(cf)
    assert out["value"] == 110000 and out["period_end"] == "2025-06-30"
    assert hist.headcount_from_companyfacts({"facts": {"dei": {}}}) is None
    assert hist.headcount_from_companyfacts({}) is None


def _fake_qfacts(rows):
    return {"total_revenue": {"tag": "RevenueFromContractWithCustomerExcludingAssessedTax",
                              "rows": rows}}


def test_history_for_ticker_quarterly(monkeypatch):
    rows = [{"period_end": "2025-03-31", "value": 120_000_000_000, "unit": "USD"},
            {"period_end": "2024-12-31", "value": 105_000_000_000, "unit": "USD"},
            {"period_end": "2024-09-30", "value": 110_000_000_000, "unit": "USD"},
            {"period_end": "2024-06-30", "value": 100_000_000_000, "unit": "USD"}]

    async def fake_company_facts(ticker):
        return {"ticker": ticker, "cik": 789019, "cik_padded": "0000789019"}

    async def fake_qfacts(cik, limit=40, companyfacts_fetch=None):
        return _fake_qfacts(rows)

    async def fake_nasdaq(url, headers=None):
        if "historical" in url:
            return {"data": {"tradesTable": {"rows": [
                {"date": "2024-06-28", "close": "$100"},
                {"date": "2024-06-30", "close": "$101"},
                {"date": "2024-09-30", "close": "$110"},
                {"date": "2024-12-31", "close": "$105"},
                {"date": "2025-03-31", "close": "$120"}]}}}
        if "dividends" in url:
            return {"data": {"dividends": {"rows": [
                {"exOrEffDate": "2024-09-30", "amount": "$1", "type": "Cash"}]}}}
        raise AssertionError(url)

    monkeypatch.setattr(hist, "async_get_company_facts", fake_company_facts)
    monkeypatch.setattr(hist, "async_get_quarterly_facts", fake_qfacts)
    out = asyncio.run(hist.history_for_ticker("MSFT", "total_revenue", fetch_json=fake_nasdaq))
    assert out["ticker"] == "MSFT" and out["frequency"] == "quarterly"
    assert [p["period_end"] for p in out["series"]] == [
        "2024-06-30", "2024-09-30", "2024-12-31", "2025-03-31"]
    assert abs(out["metric_total_change_pct"] - 20.0) < 1e-9
    tr = out["total_return"]
    assert tr is not None and len(tr["points"]) == 4
    assert tr["points"][0]["value_pct"] == 0.0
    assert tr["points"][-1]["value_pct"] > 0
    assert len(tr["metric_points"]) == 4
    assert out["read_line"]["peak_value"] == 120_000_000_000


def test_history_for_ticker_headcount(monkeypatch):
    async def fake_company_facts(ticker):
        return {"ticker": ticker, "cik": 789019, "cik_padded": "0000789019"}

    async def fake_cf(cik):
        return {"facts": {"dei": {"EntityNumberOfEmployees": {"units": {"pure": [
            {"end": "2025-06-30", "val": 228000, "fy": 2025, "form": "10-K"}]}}}}}

    monkeypatch.setattr(hist, "async_get_company_facts", fake_company_facts)
    monkeypatch.setattr(hist, "_fetch_companyfacts", fake_cf)
    out = asyncio.run(hist.history_for_ticker("MSFT", "headcount"))
    assert out["frequency"] == "annual"
    assert out["series"] == [{"period_end": "2025-06-30", "value": 228000, "label": "FY2025"}]
    assert out["total_return"] is None


def test_history_for_ticker_validation():
    try:
        asyncio.run(hist.history_for_ticker("MSFT; DROP", "total_revenue"))
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for bad ticker")
    try:
        asyncio.run(hist.history_for_ticker("MSFT", "nope"))
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for bad metric")


def test_history_for_ticker_gaap_eps(monkeypatch):
    # Feature 13: gaap_eps is an allowed history metric — the
    # trend table's EPS column reads this series. Values are raw
    # USD per share (not scaled to billions).
    assert "gaap_eps" in hist.QUARTERLY_METRICS
    assert hist.METRIC_LABELS["gaap_eps"] == "GAAP EPS"
    rows = [{"period_end": "2025-03-31", "value": 3.10, "unit": "USD"},
            {"period_end": "2024-12-31", "value": 2.90, "unit": "USD"},
            {"period_end": "2024-09-30", "value": 2.50, "unit": "USD"}]

    async def fake_company_facts(ticker):
        return {"ticker": ticker, "cik": 789019, "cik_padded": "0000789019"}

    async def fake_qfacts(cik, limit=40, companyfacts_fetch=None):
        return {"gaap_eps": {"tag": "EarningsPerShareDiluted",
                             "rows": rows}}

    async def fake_nasdaq(url, headers=None):
        return {"data": {"tradesTable": {"rows": []},
                         "dividends": {"rows": []}}}

    monkeypatch.setattr(hist, "async_get_company_facts", fake_company_facts)
    monkeypatch.setattr(hist, "async_get_quarterly_facts", fake_qfacts)
    out = asyncio.run(hist.history_for_ticker("MSFT", "gaap_eps", fetch_json=fake_nasdaq))
    assert out["metric"] == "gaap_eps" and out["unit"] == "USD"
    assert [p["value"] for p in out["series"]] == [2.50, 2.90, 3.10]
