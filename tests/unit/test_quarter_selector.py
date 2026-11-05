"""Batch 7 — quarter selector: Scout honors a requested quarter.

A requested quarter used to be a label override only: the pack
still carried latest-quarter data. These tests pin the real
behavior: the 8-K, facts, consensus and quarter end all belong
to the requested quarter, and a quarter with no filing or no
facts returns NOT_REPORTED_YET instead of mislabeled latest data.
"""

import asyncio

from mesh.scout import _pick_quarter_filing, _quarter_end_from_label, collect_evidence
from mesh.scout_async import collect_evidence_async


def _filings():
    return [
        {"form": "8-K", "filingDate": "2026-10-28", "accessionNumber": "q3",
         "primaryDocument": "d.htm", "reportDate": "2026-10-28"},
        {"form": "8-K", "filingDate": "2026-07-29", "accessionNumber": "q2",
         "primaryDocument": "d.htm", "reportDate": "2026-07-29"},
        {"form": "8-K", "filingDate": "2026-07-02", "accessionNumber": "other",
         "primaryDocument": "d.htm", "reportDate": "2026-07-02"},
        {"form": "8-K", "filingDate": "2025-07-30", "accessionNumber": "q2old",
         "primaryDocument": "d.htm", "reportDate": "2025-07-30"},
        {"form": "10-Q", "filingDate": "2026-07-29", "accessionNumber": "q2q",
         "primaryDocument": "q.htm", "reportDate": "2026-07-29"},
    ]


_CONSENSUS_BY_DATE = {
    "2026-10-28": {"status": "available", "fiscal_quarter_ending": "Sep/2026",
                   "eps_estimate": 3.0, "eps_reported": 3.1, "num_estimates": 10},
    "2026-07-29": {"status": "available", "fiscal_quarter_ending": "Jun/2026",
                   "eps_estimate": 3.0, "eps_reported": 3.0, "num_estimates": 10},
    "2025-07-30": {"status": "available", "fiscal_quarter_ending": "Jun/2025",
                   "eps_estimate": 2.0, "eps_reported": 2.0, "num_estimates": 10},
}


def _fake_mcp_call(server, tool, args):
    if server == "filings" and tool == "get_company_facts":
        return {"company_name": "Microsoft Corporation"}
    if server == "filings" and tool == "list_recent_filings":
        return {"filings": _filings()}
    if server == "filings" and tool == "get_latest_earnings_filing":
        return {"filingDate": "2026-10-28", "accessionNumber": "q3", "primaryDocument": "d.htm"}
    if server == "filings" and tool == "get_filing_text":
        return {}
    if server == "filings" and tool == "get_filing_facts":
        return {"facts": [
            {"id": "edgar_rev_2026-06-30", "metric": "total_revenue", "value": 90.007,
             "unit": "USD_B", "period": "2026-06-30", "source_tag": "Revenues", "form": "10-Q"},
            {"id": "edgar_rev_2026-09-30", "metric": "total_revenue", "value": 92.279,
             "unit": "USD_B", "period": "2026-09-30", "source_tag": "Revenues", "form": "10-Q"},
        ]}
    if server == "market" and tool == "get_quarterly_history":
        return {"quarters": [
            {"period_end": "2025-09-30", "total_revenue": 77.673e9, "operating_income": 37.961e9},
            {"period_end": "2025-12-31", "total_revenue": 85.0e9, "operating_income": 40.0e9},
            {"period_end": "2026-03-31", "total_revenue": 88.0e9, "operating_income": 41.0e9},
            {"period_end": "2026-06-30", "total_revenue": 90.007e9, "operating_income": 40.603e9},
            {"period_end": "2026-09-30", "total_revenue": 92.279e9, "operating_income": 45.915e9},
        ]}
    if server == "market" and tool == "get_price_reaction":
        return {}
    if server == "filings" and tool == "get_transcript_excerpt":
        return {"status": "unavailable"}
    if server == "estimates_news" and tool == "get_consensus_estimates":
        return dict(_CONSENSUS_BY_DATE.get(args.get("report_date", ""),
                                           {"status": "unavailable", "reason": "no row"}))
    raise AssertionError(f"unexpected call {server}/{tool}")


async def _fake_mcp_call_async(server, tool, args):
    return _fake_mcp_call(server, tool, args)


def test_quarter_end_from_label():
    assert _quarter_end_from_label("Q2 2026") == "2026-06-30"
    assert _quarter_end_from_label("Q4 2025") == "2025-12-31"
    assert _quarter_end_from_label("Q1 2026") == "2026-03-31"
    assert _quarter_end_from_label("bogus") is None
    assert _quarter_end_from_label("") is None


def test_pick_quarter_filing():
    cands = [{"filingDate": "2026-07-02", "accessionNumber": "a1"},
             {"filingDate": "2026-07-29", "accessionNumber": "a2"}]
    assert _pick_quarter_filing(cands, "2026-06-30", {"a1": None, "a2": "2026-06-30"}) == (cands[1], True)
    assert _pick_quarter_filing(cands, "2026-06-30", {"a1": None, "a2": None}) == (cands[0], False)
    assert _pick_quarter_filing([], "2026-06-30", {}) == (None, False)


def test_q2_selects_q2_filing_and_truncates():
    pack = collect_evidence("MSFT", _fake_mcp_call, quarter="Q2 2026")
    assert pack.status == "REPORTED"
    assert pack.quarter_label == "Q2 2026"
    assert str(pack.quarter_end) == "2026-06-30"
    # The Q2 8-K (2026-07-29), not the latest (2026-10-28) and not the
    # unconfirmed 2026-07-02 candidate whose consensus probe missed.
    assert pack.report_date.date().isoformat() == "2026-07-29"
    assert all(f.period <= "2026-06-30" for f in pack.facts)
    assert any(f.period == "2026-06-30" and f.source.publisher == "SEC EDGAR" for f in pack.facts)
    assert pack.consensus["fiscal_quarter_ending"] == "Jun/2026"
    assert not any("could not confirm" in m.lower() for m in pack.missing)


def test_future_quarter_not_reported():
    pack = collect_evidence("MSFT", _fake_mcp_call, quarter="Q4 2030")
    assert pack.status == "NOT_REPORTED_YET"
    assert any("Q4 2030" in m for m in pack.missing)


def test_quarter_with_filing_but_no_facts_not_reported():
    # Q2 2025 has a confirmed 8-K (2025-07-30) but no facts at or
    # before its quarter end in the available history.
    pack = collect_evidence("MSFT", _fake_mcp_call, quarter="Q2 2025")
    assert pack.status == "NOT_REPORTED_YET"
    assert any("No quarterly facts" in m for m in pack.missing)


def test_bogus_label_falls_back_to_latest():
    pack = collect_evidence("MSFT", _fake_mcp_call, quarter="bogus")
    assert pack.status == "REPORTED"
    assert pack.quarter_label == "Q3 2026"
    assert pack.report_date.date().isoformat() == "2026-10-28"
    assert any("Unrecognized quarter label" in m for m in pack.missing)


def test_unconfirmed_fallback_uses_earliest_candidate():
    def no_consensus(server, tool, args):
        if server == "estimates_news":
            return {"status": "unavailable", "reason": "no row"}
        return _fake_mcp_call(server, tool, args)

    pack = collect_evidence("MSFT", no_consensus, quarter="Q2 2026")
    assert pack.status == "REPORTED"
    assert pack.report_date.date().isoformat() == "2026-07-02"
    assert any("could not confirm" in m.lower() for m in pack.missing)


def test_consensus_mismatch_discarded():
    calls = {"n": 0}

    def flaky_consensus(server, tool, args):
        if server == "estimates_news" and args.get("report_date") == "2026-07-29":
            calls["n"] += 1
            if calls["n"] == 1:
                return {"status": "available", "fiscal_quarter_ending": "Jun/2026",
                        "eps_estimate": 3.0, "eps_reported": 3.0, "num_estimates": 10}
            return {"status": "available", "fiscal_quarter_ending": "Sep/2026",
                    "eps_estimate": 3.0, "eps_reported": 3.1, "num_estimates": 10}
        return _fake_mcp_call(server, tool, args)

    pack = collect_evidence("MSFT", flaky_consensus, quarter="Q2 2026")
    assert pack.consensus is None
    assert any("not used for beat/miss" in m for m in pack.missing)


def test_async_q2_mirror():
    pack = asyncio.run(collect_evidence_async("MSFT", _fake_mcp_call_async, quarter="Q2 2026"))
    assert pack.status == "REPORTED"
    assert pack.quarter_label == "Q2 2026"
    assert str(pack.quarter_end) == "2026-06-30"
    assert pack.report_date.date().isoformat() == "2026-07-29"
    assert all(f.period <= "2026-06-30" for f in pack.facts)


# ---- Batch 20 — fiscal quarters (non-calendar month ends) ----

def test_quarter_end_from_label_fiscal():
    assert _quarter_end_from_label("quarter ended 2026-07-26") == "2026-07-26"
    assert _quarter_end_from_label("quarter ended 2026-01-25") == "2026-01-25"
    assert _quarter_end_from_label("quarter ended 2026-02-30") is None
    assert _quarter_end_from_label("quarter ended 2026-7-6") is None
    assert _quarter_end_from_label("quarter ended bogus") is None


def test_pick_quarter_filing_month_granularity():
    # Nasdaq probes a fiscal quarter as month/year, so its month-end
    # (2026-07-31) must confirm a mid-month actual end (2026-07-26).
    cands = [{"filingDate": "2026-08-05", "accessionNumber": "a1"},
             {"filingDate": "2026-08-26", "accessionNumber": "a2"}]
    assert _pick_quarter_filing(cands, "2026-07-26", {"a1": None, "a2": "2026-07-31"}) == (cands[1], True)
    # A different month is still a mismatch, not a confirmation.
    assert _pick_quarter_filing(cands, "2026-07-26", {"a1": None, "a2": "2026-08-31"}) == (cands[0], False)


def _nvda_mcp_call(server, tool, args):
    if server == "filings" and tool == "get_company_facts":
        return {"company_name": "NVIDIA Corporation"}
    if server == "filings" and tool == "list_recent_filings":
        return {"filings": [
            {"form": "8-K", "filingDate": "2026-08-05", "accessionNumber": "other",
             "primaryDocument": "d.htm", "reportDate": "2026-08-05"},
            {"form": "8-K", "filingDate": "2026-08-26", "accessionNumber": "nq2",
             "primaryDocument": "d.htm", "reportDate": "2026-08-26"},
            {"form": "8-K", "filingDate": "2026-11-18", "accessionNumber": "nq3",
             "primaryDocument": "d.htm", "reportDate": "2026-11-18"},
        ]}
    if server == "filings" and tool == "get_filing_text":
        return {}
    if server == "filings" and tool == "get_filing_facts":
        return {"facts": [
            {"id": "edgar_rev_2026-07-26", "metric": "total_revenue", "value": 57.0,
             "unit": "USD_B", "period": "2026-07-26", "source_tag": "Revenues", "form": "10-Q"},
        ]}
    if server == "market" and tool == "get_quarterly_history":
        return {"quarters": [
            {"period_end": "2025-10-26", "total_revenue": 51.0e9, "operating_income": 31.0e9},
            {"period_end": "2026-01-25", "total_revenue": 54.0e9, "operating_income": 33.0e9},
            {"period_end": "2026-04-26", "total_revenue": 56.0e9, "operating_income": 34.0e9},
            {"period_end": "2026-07-26", "total_revenue": 57.0e9, "operating_income": 35.0e9},
            {"period_end": "2026-10-26", "total_revenue": 60.0e9, "operating_income": 37.0e9},
        ]}
    if server == "market" and tool == "get_price_reaction":
        return {}
    if server == "filings" and tool == "get_transcript_excerpt":
        return {"status": "unavailable"}
    if server == "estimates_news" and tool == "get_consensus_estimates":
        if args.get("report_date") == "2026-08-26":
            return {"status": "available", "fiscal_quarter_ending": "Jul/2026",
                    "eps_estimate": 4.0, "eps_reported": 4.2, "num_estimates": 12}
        return {"status": "unavailable", "reason": "no row"}
    raise AssertionError(f"unexpected call {server}/{tool}")


def test_fiscal_quarter_selects_fiscal_filing_and_truncates():
    pack = collect_evidence("NVDA", _nvda_mcp_call, quarter="quarter ended 2026-07-26")
    assert pack.status == "REPORTED"
    assert pack.quarter_label == "quarter ended 2026-07-26"
    assert str(pack.quarter_end) == "2026-07-26"
    # The earnings 8-K (2026-08-26), confirmed by the Jul/2026 probe
    # at month granularity — not the unconfirmed 2026-08-05 candidate.
    assert pack.report_date.date().isoformat() == "2026-08-26"
    assert all(f.period <= "2026-07-26" for f in pack.facts)
    assert any(f.period == "2026-07-26" and f.source.publisher == "SEC EDGAR" for f in pack.facts)
    # Consensus survives the month-granularity guard, so beat/miss
    # still works for a fiscal quarter.
    assert pack.consensus["fiscal_quarter_ending"] == "Jul/2026"
    assert not any("could not confirm" in m.lower() for m in pack.missing)
    assert not any("not used for beat/miss" in m for m in pack.missing)


# Batch 20 fix (Nov 4, 2026): the ASYNC Scout's consensus guard
# was exact-date while the sync guard went month-granular, so
# every fiscal quarter's consensus was discarded on the cloud
# path (live NVDA runs showed "Consensus unavailable" notes and
# no beat/miss). This mirrors the sync fiscal test through
# collect_evidence_async: requested April quarter, Nasdaq row
# "Apr/2026" (month-end 2026-04-30) vs actual end 2026-04-26 —
# same fiscal month, so the consensus must survive.
def _nvda_april_mcp_call(server, tool, args):
    if server == "filings" and tool == "get_company_facts":
        return {"ticker": "NVDA", "company_name": "NVIDIA Corporation", "cik": 1045810}
    if server == "filings" and tool == "list_recent_filings":
        return {"filings": [
            {"form": "8-K", "filingDate": "2026-05-27", "accessionNumber": "nq1",
             "primaryDocument": "d.htm", "reportDate": "2026-05-27"},
            {"form": "8-K", "filingDate": "2026-02-25", "accessionNumber": "old",
             "primaryDocument": "d.htm", "reportDate": "2026-02-25"},
        ]}
    if server == "filings" and tool == "get_filing_text":
        return {}
    if server == "filings" and tool == "get_filing_facts":
        return {"facts": [
            {"id": "edgar_rev_2026-04-26", "metric": "total_revenue", "value": 44.0,
             "unit": "USD_B", "period": "2026-04-26", "source_tag": "Revenues", "form": "10-Q"},
        ]}
    if server == "market" and tool == "get_quarterly_history":
        return {"quarters": [
            {"period_end": "2025-04-27", "total_revenue": 26.0e9, "operating_income": 17.0e9},
            {"period_end": "2026-04-26", "total_revenue": 44.0e9, "operating_income": 28.0e9},
        ]}
    if server == "market" and tool == "get_price_reaction":
        return {}
    if server == "filings" and tool == "get_transcript_excerpt":
        return {"status": "unavailable"}
    if server == "estimates_news" and tool == "get_consensus_estimates":
        # Selection probes AND the Phase B call both use the
        # selected filing's date (2026-05-27); one rule covers both.
        if args.get("report_date") == "2026-05-27":
            return {"status": "available", "fiscal_quarter_ending": "Apr/2026",
                    "eps_estimate": 0.90, "eps_reported": 0.95, "num_estimates": 10}
        return {"status": "unavailable", "reason": "no row"}
    raise AssertionError(f"unexpected call {server}/{tool}")


async def _nvda_april_mcp_call_async(server, tool, args):
    return _nvda_april_mcp_call(server, tool, args)


def test_async_fiscal_quarter_keeps_month_granularity_consensus():
    pack = asyncio.run(collect_evidence_async(
        "NVDA", _nvda_april_mcp_call_async, quarter="quarter ended 2026-04-26"))
    assert pack.status == "REPORTED"
    assert pack.quarter_label == "quarter ended 2026-04-26"
    assert str(pack.quarter_end) == "2026-04-26"
    assert pack.report_date.date().isoformat() == "2026-05-27"
    assert all(f.period <= "2026-04-26" for f in pack.facts)
    # The guard must NOT discard the April row: 2026-04-30 and
    # 2026-04-26 are the same fiscal month.
    assert pack.consensus is not None
    assert pack.consensus["fiscal_quarter_ending"] == "Apr/2026"
    assert not any("not used for beat/miss" in m for m in pack.missing)


# ---- Nov 4, 2026 — requested-quarter candidate window (limit 300) ----

def _window_filings():
    # 120 filings, newest first (SEC order). The earnings 8-K sits
    # at index 100 — outside a 50-row window, inside a 300-row one.
    out = [{"form": "8-K", "filingDate": "2026-06-30", "accessionNumber": f"filler-{i}",
            "primaryDocument": "d.htm", "reportDate": "2026-06-30"} for i in range(100)]
    out.append({"form": "8-K", "filingDate": "2026-05-20", "accessionNumber": "earn-q1",
                "primaryDocument": "d.htm", "reportDate": "2026-05-20"})
    out.append({"form": "8-K", "filingDate": "2026-05-08", "accessionNumber": "pre-1",
                "primaryDocument": "d.htm", "reportDate": "2026-05-08"})
    out.append({"form": "8-K", "filingDate": "2026-04-27", "accessionNumber": "pre-2",
                "primaryDocument": "d.htm", "reportDate": "2026-04-27"})
    out += [{"form": "8-K", "filingDate": "2026-04-10", "accessionNumber": f"old-{i}",
             "primaryDocument": "d.htm", "reportDate": "2026-04-10"} for i in range(17)]
    return out


def _window_mcp_call(server, tool, args):
    if server == "filings" and tool == "get_company_facts":
        return {"company_name": "NVIDIA Corporation"}
    if server == "filings" and tool == "list_recent_filings":
        # The fake honours the limit, like the real tool: the window
        # is a client-side slice of the submissions recent array.
        return {"filings": _window_filings()[: args.get("limit", 10)]}
    if server == "filings" and tool == "get_filing_text":
        return {}
    if server == "filings" and tool == "get_filing_facts":
        return {"facts": [
            {"id": "edgar_rev_2026-04-26", "metric": "total_revenue", "value": 81.615,
             "unit": "USD_B", "period": "2026-04-26", "source_tag": "Revenues", "form": "10-Q"},
            {"id": "edgar_rev_2025-04-27", "metric": "total_revenue", "value": 44.062,
             "unit": "USD_B", "period": "2025-04-27", "source_tag": "Revenues", "form": "10-Q"},
        ]}
    if server == "market" and tool == "get_quarterly_history":
        return {"quarters": [
            {"period_end": "2025-04-27", "total_revenue": 44.062e9, "operating_income": 21.6e9},
            {"period_end": "2025-07-27", "total_revenue": 46.743e9, "operating_income": 28.4e9},
            {"period_end": "2025-10-26", "total_revenue": 57.006e9, "operating_income": 36.0e9},
            {"period_end": "2026-04-26", "total_revenue": 81.615e9, "operating_income": 53.5e9},
        ]}
    if server == "market" and tool == "get_price_reaction":
        return {}
    if server == "filings" and tool == "get_transcript_excerpt":
        return {"status": "unavailable"}
    if server == "estimates_news" and tool == "get_consensus_estimates":
        if args.get("report_date") == "2026-05-20":
            return {"status": "available", "fiscal_quarter_ending": "Apr/2026",
                    "eps_estimate": None, "eps_reported": 2.39, "num_estimates": None}
        return {"status": "unavailable", "reason": "no row"}
    raise AssertionError(f"unexpected call {server}/{tool}")


async def _window_mcp_call_async(server, tool, args):
    return _window_mcp_call(server, tool, args)


def test_requested_quarter_finds_earnings_8k_beyond_50_rows():
    # NVDA, Nov 2026: the May 20, 2026 earnings 8-K sat beyond the
    # old 50-row recent-filings window, so the April pick fell back
    # to a June 30 non-earnings 8-K and consensus anchored to the
    # wrong date. With the 300-row window the probe confirms it.
    pack = collect_evidence("NVDA", _window_mcp_call, quarter="quarter ended 2026-04-26")
    assert pack.status == "REPORTED"
    assert pack.quarter_label == "quarter ended 2026-04-26"
    assert pack.report_date.date().isoformat() == "2026-05-20"
    assert pack.consensus is not None
    assert pack.consensus["fiscal_quarter_ending"] == "Apr/2026"
    assert pack.consensus["eps_reported"] == 2.39
    assert not any("could not confirm" in m.lower() for m in pack.missing)


def test_async_requested_quarter_finds_earnings_8k_beyond_50_rows():
    pack = asyncio.run(collect_evidence_async(
        "NVDA", _window_mcp_call_async, quarter="quarter ended 2026-04-26"))
    assert pack.status == "REPORTED"
    assert pack.report_date.date().isoformat() == "2026-05-20"
    assert pack.consensus is not None
    assert pack.consensus["fiscal_quarter_ending"] == "Apr/2026"
