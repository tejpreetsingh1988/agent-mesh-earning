"""Past earnings reactions (Feature 20): 8-K identification from
fixture submissions + index listings (75-day window, 99.1
shape), the Batch 28 window rule on weekend report dates,
and the missing-reaction "—" case. Network is stubbed
throughout; the live GOOGL check is the C1 composition
check, not a unit test."""
import asyncio

import pytest

from mesh import past_reactions as pr


def _recent(forms, filing_dates, report_dates, accessions):
    return {"form": forms, "filingDate": filing_dates,
            "reportDate": report_dates, "accessionNumber": accessions}


def _googl_recent():
    # 10-Qs newest first; 8-Ks after each quarter end.
    return _recent(
        ["10-Q", "8-K", "8-K", "10-Q", "8-K", "10-Q", "8-K", "10-Q", "8-K"],
        ["2026-10-29", "2026-10-28", "2026-11-15", "2026-07-29", "2026-07-28",
         "2026-04-29", "2026-04-28", "2026-01-29", "2026-01-28"],
        ["2026-09-30", "2026-09-30", "2026-09-30", "2026-06-30", "2026-06-30",
         "2026-03-31", "2026-03-31", "2025-12-31", "2025-12-31"],
        ["000165204426000001", "000165204426000002", "000165204426000003",
         "000165204426000004", "000165204426000005", "000165204426000006",
         "000165204426000007", "000165204426000008", "000165204426000009"])


def test_quarter_ends_from_recent():
    assert pr.quarter_ends_from_recent(_googl_recent()) == [
        "2026-09-30", "2026-06-30", "2026-03-31", "2025-12-31"]


def test_earnings_8k_candidates_window():
    recent = _googl_recent()
    # Q3 2026: 8-Ks on Oct 28 (28 days after) and Nov 15 (46 days
    # after) both in the 75-day window, earliest first.
    assert pr.earnings_8k_candidates(recent, "2026-09-30") == [
        ("2026-10-28", "000165204426000002"),
        ("2026-11-15", "000165204426000003")]
    # An 8-K filed ON the quarter end does not count.
    only_on = _recent(["10-Q", "8-K"], ["2026-10-28", "2026-10-28"],
                      ["2026-09-30", "2026-09-30"], ["acc1", "acc2"])
    assert pr.earnings_8k_candidates(only_on, "2026-10-28") == []


def test_identify_8k_skips_candidate_without_991():
    recent = _googl_recent()

    async def fetch_json(url, headers=None):
        # The Oct 28 8-K's index has no 99.1; the Nov 15 one's does.
        if "000165204426000002" in url:
            return {"directory": {"item": [{"name": "goog-8k_20261028.htm"}]}}
        if "000165204426000003" in url:
            return {"directory": {"item": [{"name": "ex99-1.htm"}, {"name": "goog-8k.htm"}]}}
        raise AssertionError(url)

    found = asyncio.run(pr._identify_8k(1652044, recent, "2026-09-30", fetch_json))
    assert found == ("2026-11-15", "000165204426000003")


def test_identify_8k_none_when_no_991_anywhere():
    recent = _googl_recent()

    async def fetch_json(url, headers=None):
        return {"directory": {"item": [{"name": "goog-8k.htm"}]}}

    assert asyncio.run(pr._identify_8k(1652044, recent, "2026-09-30", fetch_json)) is None


def _nasdaq_body(closes):
    # closes: [(MM/DD/YYYY, "$close")] newest-first, as Nasdaq returns.
    return {"data": {"tradesTable": {"rows": [
        {"date": d, "close": c, "open": c, "volume": "1000"} for d, c in closes]}}}


def _fetch_for(index_map, nasdaq_body):
    async def fetch_json(url, headers=None):
        if "sec.gov" in url:
            for acc, items in index_map.items():
                if acc in url:
                    return {"directory": {"item": [{"name": n} for n in items]}}
            return {"directory": {"item": []}}
        if "nasdaq.com" in url:
            return nasdaq_body
        raise AssertionError(url)
    return fetch_json


def test_row_googl_proven_window():
    recent = _googl_recent()
    fetch = _fetch_for(
        {"000165204426000002": ["ex99-1.htm"]},
        _nasdaq_body([("10/29/2026", "$283.82"), ("10/28/2026", "$324.89"),
                      ("10/27/2026", "$320.00")]))
    row = asyncio.run(pr._row_for_quarter("GOOGL", 1652044, recent, "2026-09-30", fetch))
    assert row == {"quarter_end": "2026-09-30", "report_date": "2026-10-28",
                   "close_before": 324.89, "close_after": 283.82, "change_pct": -12.6}


def test_row_weekend_report_date():
    recent = _recent(["10-Q", "8-K"], ["2026-10-30", "2026-10-30"],
                     ["2026-09-30", "2026-09-30"], ["acc1", "acc2"])
    # Report date is a Friday: base is Friday's close, reaction
    # is Monday's — the weekend never invents a close.
    fetch = _fetch_for(
        {"acc2": ["a2026-q3_ex991.htm"]},
        _nasdaq_body([("11/02/2026", "$105.00"), ("10/30/2026", "$100.00"),
                      ("10/29/2026", "$99.00")]))
    row = asyncio.run(pr._row_for_quarter("TEST", 1, recent, "2026-09-30", fetch))
    assert row["report_date"] == "2026-10-30"
    assert row["close_before"] == 100.0
    assert row["close_after"] == 105.0
    assert row["change_pct"] == 5.0


def test_row_missing_reaction_is_none():
    recent = _recent(["10-Q", "8-K"], ["2026-10-30", "2026-10-28"],
                     ["2026-09-30", "2026-09-30"], ["acc1", "acc2"])
    # The report date is the last close in the fixture: no close
    # after it yet — "—", not a partial move.
    fetch = _fetch_for(
        {"acc2": ["ex99-1.htm"]},
        _nasdaq_body([("10/28/2026", "$324.89"), ("10/27/2026", "$320.00")]))
    row = asyncio.run(pr._row_for_quarter("TEST", 1, recent, "2026-09-30", fetch))
    assert row["close_before"] == 324.89
    assert row["close_after"] is None
    assert row["change_pct"] is None


def test_row_omitted_when_no_earnings_8k():
    recent = _recent(["10-Q"], ["2026-10-29"], ["2026-09-30"], ["acc1"])
    fetch = _fetch_for({}, _nasdaq_body([]))
    assert asyncio.run(pr._row_for_quarter("TEST", 1, recent, "2026-09-30", fetch)) is None


def test_past_reactions_counts_omitted(monkeypatch):
    recent = _googl_recent()

    async def fake_facts(ticker):
        return {"ticker": "GOOGL", "cik": 1652044, "cik_padded": "0001652044"}

    async def fake_submissions(padded):
        return {"filings": {"recent": recent}}

    monkeypatch.setattr(pr, "async_get_company_facts", fake_facts)
    monkeypatch.setattr(pr, "_submissions", fake_submissions)
    # One body covering all four windows: a close on, just
    # before, and just after each report date.
    fetch = _fetch_for(
        {"000165204426000002": ["ex99-1.htm"],
         "000165204426000005": ["ex99-1.htm"],
         "000165204426000007": ["ex99-1.htm"],
         "000165204426000009": ["ex99-1.htm"]},
        _nasdaq_body([
            ("10/29/2026", "$283.82"), ("10/28/2026", "$324.89"),
            ("10/27/2026", "$320.00"),
            ("07/29/2026", "$205.00"), ("07/28/2026", "$200.00"),
            ("07/27/2026", "$198.00"),
            ("04/29/2026", "$175.00"), ("04/28/2026", "$170.00"),
            ("04/27/2026", "$168.00"),
            ("01/29/2026", "$155.00"), ("01/28/2026", "$150.00"),
            ("01/27/2026", "$148.00")]))
    out = asyncio.run(pr.past_reactions_for_ticker("GOOGL", fetch))
    assert out["ticker"] == "GOOGL"
    assert len(out["rows"]) == 4
    assert out["rows"][0]["quarter_end"] == "2026-09-30"
    assert out["omitted"] == 0


def test_past_reactions_bad_ticker():
    with pytest.raises(ValueError):
        asyncio.run(pr.past_reactions_for_ticker("!!!"))
