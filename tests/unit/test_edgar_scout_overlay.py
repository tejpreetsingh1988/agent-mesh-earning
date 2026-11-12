"""Phase 1 Scout wiring: EDGAR facts overlay yfinance, Q4 derived.

Scout's fake MCP here returns BOTH a yfinance row and an EDGAR
row for the same period. The pack must contain the EDGAR value
(filing-verified wins), the yfinance value must not survive as a
duplicate, and the old 'not yet parsed' missing note must be gone.
"""
from mesh.edgar_facts import derive_q4_rows
from mesh.scout import collect_evidence


def _row(start, end, val, form="10-Q", fp="Q3"):
    return {"start": start, "end": end, "val": val, "form": form,
            "fp": fp, "filed": "2026-10-28", "accn": "0000000000-26-000001"}


def test_derive_q4_fy_minus_ytd():
    concept = {"units": {"USD": [
        _row("2026-01-01", "2026-09-30", 300000000000, fp="Q3"),  # 9m YTD, 272 days
        _row("2026-01-01", "2026-12-31", 400000000000, form="10-K", fp="FY"),  # 364 days
    ]}}
    rows = derive_q4_rows(concept, "total_revenue")
    assert len(rows) == 1
    assert rows[0]["value"] == 100000000000
    assert rows[0]["derived"] is True
    assert rows[0]["period_end"] == "2026-12-31"


def _scout_mcp_with_edgar():
    def fake(server, tool, args):
        if tool == "get_company_facts":
            return {"ticker": "GOOGL", "company_name": "Alphabet Inc.", "cik": 1652044}
        if tool == "get_latest_earnings_filing":
            return {"filingDate": "2026-10-28", "accessionNumber": "0001652044-26-000080",
                    "primaryDocument": "goog-20261028.htm"}
        if tool == "list_recent_filings":
            return {"filings": [{"accessionNumber": "0001652044-26-000080", "reportDate": "2026-09-30"}]}
        if tool == "get_filing_text":
            return {"excerpt": "Alphabet Inc. Q3 2026", "char_count": 100}
        if tool == "get_price_reaction":
            return {"closes": [{"date": "2026-10-28", "close": 324.89}]}
        if tool == "get_consensus_estimates":
            return {"status": "available", "eps_estimate": 2.94, "eps_reported": 2.12,
                    "num_estimates": 14, "fiscal_quarter_ending": "Sep/2026"}
        if tool == "get_transcript_excerpt":
            return {"status": "unavailable", "reason": "no page"}
        if tool == "get_filing_facts":
            return {"ticker": "GOOGL", "cik": 1652044, "missing": [], "facts": [
                {"id": "edgar_total_revenue_2026-09-30", "metric": "total_revenue",
                 "value": 127.577, "unit": "USD_B", "period": "2026-09-30",
                 "source_tag": "Revenues", "derived": False, "derivation": "",
                 "form": "10-Q", "filed": "2026-10-28"},
            ]}
        raise AssertionError(f"unexpected {server}/{tool}")
    return fake


def test_scout_edgar_facts_are_the_series():
    # Batch 64: the yfinance leg is retired — the pack's facts
    # come from SEC EDGAR XBRL alone, one fact per metric+period.
    pack = collect_evidence("GOOGL", _scout_mcp_with_edgar())
    revs = [f for f in pack.facts if f.metric == "total_revenue" and f.period == "2026-09-30"]
    assert len(revs) == 1, "no duplicate metric+period"
    assert revs[0].value == 127.577
    assert revs[0].source.publisher == "SEC EDGAR"
    assert not any("not yet parsed" in m for m in pack.missing)


def test_scout_no_cross_check_note_without_yfinance():
    """The cross-check note compared EDGAR against the yfinance
    base series. With that leg retired (Batch 64) there is
    nothing to cross-check against, so no note is emitted —
    and the EDGAR fact is still the one in the pack."""
    pack = collect_evidence("GOOGL", _scout_mcp_with_edgar())
    rev = next(f for f in pack.facts if f.metric == "total_revenue" and f.period == "2026-09-30")
    assert rev.value == 127.577
    assert not any("Cross-check" in m for m in pack.missing)
