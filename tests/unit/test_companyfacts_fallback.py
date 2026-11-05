"""Companyfacts fallback (ADR 021): when EDGAR's per-tag
companyconcept endpoint returns empty units for a filer's
current tag (Visa, Nov 2, 2026), the quarterly pick must fall
back to the same tags read from the one companyfacts payload
— and only then. Working tickers never trigger it.

Convention, as elsewhere in this repo: sync test functions
wrapping asyncio.run for the async path; fixtures duplicated
in this file, not imported from other test files.
"""

import asyncio

from mesh import async_tools
from mesh.edgar_facts import (
    ALTERNATE_TAGS,
    get_quarterly_facts,
)

CURRENT = "RevenueFromContractWithCustomerExcludingAssessedTax"
RETIRED = "Revenues"


def _row(start, end, val):
    return {"form": "10-Q", "start": start, "end": end, "val": val,
            "filed": "2026-01-01", "accn": "0000000000-00-000000"}


def _concept(rows):
    return {"units": {"USD": rows}}


# Visa-shaped fixtures: companyconcept has stale Revenues rows
# and EMPTY units for the current tag (the real failure mode —
# valid JSON, zero rows); companyfacts has the current tag
# through 2026-03-31.
_CONCEPT = {
    RETIRED: _concept([
        _row("2019-01-01", "2019-03-31", 5.494e9),
        _row("2019-04-01", "2019-06-30", 5.84e9),
    ]),
    CURRENT: {"units": {"USD": {}}},
}
_COMPANYFACTS = {"facts": {"us-gaap": {CURRENT: {"units": {"USD": [
    _row("2025-04-01", "2025-06-30", 10.17e9),
    _row("2025-07-01", "2025-09-30", 10.72e9),
    _row("2025-10-01", "2025-12-31", 11.23e9),
    _row("2026-01-01", "2026-03-31", 11.23e9),
]}}}}}


def _visa_concept(cik, tag):
    return _CONCEPT.get(tag, {"units": {}})


def test_stale_pick_falls_back_to_companyfacts():
    calls = []

    def fake_cf(cik):
        calls.append(cik)
        return _COMPANYFACTS

    out = get_quarterly_facts(1403161, fetch=_visa_concept,
                              report_date="2026-10-27",
                              companyfacts_fetch=fake_cf)
    assert out["total_revenue"]["tag"] == CURRENT
    assert out["total_revenue"]["rows"][0]["period_end"] == "2026-03-31"
    # Fetched once per run, not once per metric, even though
    # every metric's pick also needed the fallback.
    assert calls == [1403161]


def test_fresh_pick_never_touches_companyfacts():
    # Every tag fresh, so no metric's pick needs the fallback.
    # (A fresh pick for one metric alone would still let other
    # metrics' empty picks trigger it — that is correct too.)
    # The fixture carries BOTH a duration row (for flow
    # metrics) and an instant row (for balance metrics:
    # cash, short-term investments), so every metric's pick
    # is fresh — otherwise the instant metrics' empty picks
    # would correctly trigger the fallback and fail this test.
    def fresh_concept(cik, tag):
        return _concept([_row("2026-07-01", "2026-09-30", 77.0e9),
                         {"form": "10-Q", "end": "2026-09-30", "val": 77.0e9,
                          "filed": "2026-01-01", "accn": "0000000000-00-000000"}])

    calls = []

    def counting_cf(cik):
        calls.append(cik)
        return _COMPANYFACTS

    out = get_quarterly_facts(789019, fetch=fresh_concept,
                              report_date="2026-10-27",
                              companyfacts_fetch=counting_cf)
    # Fresh everywhere: the pick's newest row is current, and
    # the fallback never ran (its tag is whichever alternate
    # tag wins the recency tie — not the point of this test).
    assert out["total_revenue"]["rows"][0]["period_end"] == "2026-09-30"
    assert calls == []


def test_stale_pick_without_report_date_keeps_old_pick():
    # Without a report date the staleness check cannot run, so
    # the stale total_revenue pick survives. (Other metrics'
    # empty picks still trigger the fallback — that path needs
    # no date — so no call-count assertion belongs here.)
    out = get_quarterly_facts(1403161, fetch=_visa_concept,
                              report_date=None,
                              companyfacts_fetch=lambda cik: _COMPANYFACTS)
    assert out["total_revenue"]["tag"] == RETIRED


def test_empty_pick_falls_back_without_report_date():
    def empty_concept(cik, tag):
        return {"units": {}}

    out = get_quarterly_facts(1403161, fetch=empty_concept,
                              report_date=None,
                              companyfacts_fetch=lambda cik: _COMPANYFACTS)
    assert out["total_revenue"]["tag"] == CURRENT
    assert out["total_revenue"]["rows"][0]["period_end"] == "2026-03-31"


def test_async_stale_pick_falls_back_to_companyfacts(monkeypatch):
    async def fake_fetch(cik, tag):
        return _CONCEPT.get(tag, {"units": {}})

    calls = []

    async def fake_cf(cik):
        calls.append(cik)
        return _COMPANYFACTS

    monkeypatch.setattr(async_tools, "_fetch_concept", fake_fetch)
    out = asyncio.run(async_tools.async_get_quarterly_facts(
        1403161, report_date="2026-10-27", companyfacts_fetch=fake_cf))
    assert out["total_revenue"]["tag"] == CURRENT
    assert out["total_revenue"]["rows"][0]["period_end"] == "2026-03-31"
    assert calls == [1403161]


def test_async_fresh_pick_never_touches_companyfacts(monkeypatch):
    async def fresh_fetch(cik, tag):
        return _concept([_row("2026-07-01", "2026-09-30", 77.0e9),
                         {"form": "10-Q", "end": "2026-09-30", "val": 77.0e9,
                          "filed": "2026-01-01", "accn": "0000000000-00-000000"}])

    calls = []

    async def counting_cf(cik):
        calls.append(cik)
        return _COMPANYFACTS

    monkeypatch.setattr(async_tools, "_fetch_concept", fresh_fetch)
    out = asyncio.run(async_tools.async_get_quarterly_facts(
        789019, report_date="2026-10-27", companyfacts_fetch=counting_cf))
    assert out["total_revenue"]["rows"][0]["period_end"] == "2026-09-30"
    assert calls == []


# Sanity: the fallback reads only the alternate tags, so a
# companyfacts payload missing a metric's tags still reports
# that metric missing (with the fallback note) instead of
# crashing or inventing a row.
def test_fallback_missing_metric_reports_missing():
    out = get_quarterly_facts(1403161, fetch=_visa_concept,
                              report_date="2026-10-27",
                              companyfacts_fetch=lambda cik: _COMPANYFACTS)
    assert any("operating_income" in m and "companyfacts fallback also empty" in m
               for m in out["missing"])


def test_alternate_tags_cover_current_tag():
    assert CURRENT in ALTERNATE_TAGS["total_revenue"]
