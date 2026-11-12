"""Batch 65 — 6-K support for foreign private issuers (Nebius).

No live network: the NBIS Q3 2026 release (exhibit 99.1) and its
6-K shell are vendored fixtures under tests/fixtures/ (public
SEC filings). The Scout packs are built from fake MCP clients.
"""
import asyncio
from datetime import date
from pathlib import Path

import pytest

from mesh.analyst import analyse
from mesh.kpi import pick_earnings_8k
from mesh.past_reactions import earnings_8k_candidates
from mesh.release_facts import extract_release_facts, quarter_end_from_release
from mesh.schemas import EvidencePack, Fact, SourceRef
from mesh.scout import collect_evidence
from mesh.scout_async import collect_evidence_async

FIX = Path(__file__).parent.parent / "fixtures"
EXHIBIT = (FIX / "nbis_ex99-1.txt").read_text()
SHELL = (FIX / "nbis_6k_shell.txt").read_text()

EXHIBIT_NAME = "tm2629571d1_ex99-1.htm"
ACC = "0001104659-26-126008"
EXHIBIT_URL = f"https://www.sec.gov/Archives/edgar/data/1513845/000110465926126008/{EXHIBIT_NAME}"


# --- release_facts: the parser -------------------------------------------

def test_release_facts_parse_nbis_fixture():
    r = extract_release_facts(EXHIBIT, ticker="NBIS", quarter_end=date(2026, 9, 30),
                              exhibit_url=EXHIBIT_URL, filing_date="2026-11-12")
    assert r["missing"] == []
    by_key = {(f["metric"], f["period"]): f["value"] for f in r["facts"]}
    assert by_key[("total_revenue", "2026-09-30")] == 0.9808
    assert by_key[("total_revenue", "2025-09-30")] == 0.1461
    assert by_key[("net_income", "2026-09-30")] == -0.0375
    assert by_key[("net_income", "2025-09-30")] == -0.1196
    assert by_key[("adjusted_ebitda", "2026-09-30")] == 0.4658
    assert by_key[("adjusted_ebitda", "2025-09-30")] == -0.0052
    assert by_key[("adjusted_net_income", "2026-09-30")] == 0.0909
    assert by_key[("adjusted_net_income", "2025-09-30")] == -0.1004
    assert by_key[("shares_outstanding", "2026-09-30")] == 292902405.0
    assert all(f["unit"] == "USD_B" for f in r["facts"] if f["metric"] != "shares_outstanding")
    assert all("6-K exhibit 99.1" in f["publisher"] for f in r["facts"])


def test_release_facts_rejects_tampered_row():
    # The revenue row's stated change is 571%; tamper it to 999%
    # and the row must be skipped (never guessed), with a note.
    tampered = EXHIBIT.replace("571 %", "999 %", 1)
    r = extract_release_facts(tampered, ticker="NBIS", quarter_end=date(2026, 9, 30),
                              exhibit_url=EXHIBIT_URL, filing_date="2026-11-12")
    assert not any(f["metric"] == "total_revenue" for f in r["facts"])
    assert any("Revenues" in m for m in r["missing"])
    # The other rows still parse.
    assert any(f["metric"] == "net_income" for f in r["facts"])


def test_release_facts_parse_cleaned_exhibit():
    # Batch 71: the production path cleans the exhibit with
    # _clean_html before parsing. The old cleaner collapsed all
    # whitespace to one line, which broke the parser's line-start
    # anchored labels — the live NBIS run (Nov 12) emitted only
    # shares_outstanding and four "could not verify" notes. The
    # fixture must survive cleaning with its rows intact.
    from mesh.edgar import _clean_html
    cleaned = _clean_html(EXHIBIT)
    assert "\n" in cleaned
    r = extract_release_facts(cleaned, ticker="NBIS", quarter_end=date(2026, 9, 30),
                              exhibit_url=EXHIBIT_URL, filing_date="2026-11-12")
    assert r["missing"] == []
    by_key = {(f["metric"], f["period"]): f["value"] for f in r["facts"]}
    assert by_key[("total_revenue", "2026-09-30")] == 0.9808
    assert by_key[("adjusted_ebitda", "2026-09-30")] == 0.4658
    assert by_key[("shares_outstanding", "2026-09-30")] == 292902405.0


def test_quarter_end_from_release():
    assert quarter_end_from_release(EXHIBIT) == date(2026, 9, 30)
    assert quarter_end_from_release("no period stated here") is None
    assert quarter_end_from_release("results for the quarter ended June 30, 2026") == date(2026, 6, 30)


# --- edgar: the 6-K branch -------------------------------------------------

def _nbis_submissions():
    return {"filings": {"recent": {
        "form": ["6-K", "20-F", "6-K"],
        "filingDate": ["2026-11-12", "2026-04-30", "2026-08-13"],
        "accessionNumber": [ACC, "0001104659-26-000001", "0001104659-26-000002"],
        "primaryDocument": ["tm2629571d1_6k.htm", "tm25_20f.htm", "tm26_6k.htm"],
    }}}


def test_edgar_latest_earnings_filing_picks_results_6k(monkeypatch):
    import mesh.edgar as edgar
    monkeypatch.setattr(edgar, "get_company_facts", lambda t: {
        "ticker": "NBIS", "company_name": "Nebius Group N.V.", "cik": 1513845,
        "cik_padded": "0001513845"})
    monkeypatch.setattr(edgar, "_submissions", lambda cik_padded: _nbis_submissions())
    monkeypatch.setattr(edgar, "get_filing_text", lambda *a, **k: {"excerpt": SHELL})
    monkeypatch.setattr(edgar, "_filing_index_items", lambda cik, acc: [
        {"name": EXHIBIT_NAME}, {"name": "tm2629571d1_ex99-2.htm"}])
    out = edgar.get_latest_earnings_filing("NBIS")
    assert out["form"] == "6-K"
    assert out["filing_kind"] == "6-K"
    assert out["primaryDocument"] == EXHIBIT_NAME
    assert out["url"] == EXHIBIT_URL
    assert out["accessionNumber"] == ACC


def test_is_results_6k_text_requires_both_halves():
    import mesh.edgar as edgar
    assert edgar._is_results_6k_text(SHELL) is True
    assert edgar._is_results_6k_text("Filed as Exhibit 99.1 is a shareholder letter.") is False
    assert edgar._is_results_6k_text("announcing financial results, no exhibit named") is False


# --- kpi / past_reactions: the 6-K fallback -------------------------------

def test_pick_earnings_8k_falls_back_to_6k():
    recent = {"form": ["6-K", "20-F"], "filingDate": ["2026-11-12", "2026-04-30"],
              "accessionNumber": [ACC, "0001104659-26-000001"]}
    assert pick_earnings_8k(recent, "2026-09-30") == ACC
    # An 8-K in the window still wins over the 6-K.
    recent8 = {"form": ["8-K", "6-K"], "filingDate": ["2026-10-28", "2026-11-12"],
               "accessionNumber": ["0001652044-26-000080", ACC]}
    assert pick_earnings_8k(recent8, "2026-09-30") == "0001652044-26-000080"
    assert pick_earnings_8k(recent, "2020-01-01") is None


def test_earnings_8k_candidates_falls_back_to_6k():
    recent = {"form": ["6-K"], "filingDate": ["2026-11-12"], "accessionNumber": [ACC]}
    assert earnings_8k_candidates(recent, "2026-09-30") == [("2026-11-12", ACC)]
    assert earnings_8k_candidates(recent, "2020-01-01") == []


# --- Scout packs -----------------------------------------------------------

def _nbis_filing():
    return {"ticker": "NBIS", "company_name": "Nebius Group N.V.", "cik": 1513845,
            "form": "6-K", "filingDate": "2026-11-12", "accessionNumber": ACC,
            "primaryDocument": EXHIBIT_NAME, "url": EXHIBIT_URL, "filing_kind": "6-K"}


def _nbis_fake(server, tool, args=None):
    args = args or {}
    if (server, tool) == ("filings", "get_company_facts"):
        return {"ticker": "NBIS", "company_name": "Nebius Group N.V.", "cik": 1513845}
    if (server, tool) == ("filings", "get_latest_earnings_filing"):
        return _nbis_filing()
    if (server, tool) == ("filings", "list_recent_filings"):
        return {"filings": [
            {"form": "6-K", "filingDate": "2026-11-12", "accessionNumber": ACC,
             "primaryDocument": EXHIBIT_NAME, "reportDate": "2026-11-12", "url": EXHIBIT_URL},
            {"form": "20-F", "filingDate": "2026-04-30", "accessionNumber": "0001104659-26-000001",
             "primaryDocument": "tm25_20f.htm", "reportDate": "2025-12-31", "url": "https://example/20f"},
        ]}
    if (server, tool) == ("filings", "get_filing_text"):
        return {"excerpt": EXHIBIT, "url": EXHIBIT_URL, "char_count": len(EXHIBIT)}
    if (server, tool) == ("filings", "get_filing_facts"):
        return {"facts": [], "missing": []}  # no XBRL for a 6-K filer
    if (server, tool) == ("market", "get_price_reaction"):
        return {"closes": [{"date": "2026-11-12", "close": 45.0}], "source": "Nasdaq (free)"}
    if (server, tool) == ("estimates_news", "get_consensus_estimates"):
        return {"status": "available", "eps_estimate": -0.13, "eps_reported": -0.13,
                "num_estimates": 12, "fiscal_quarter_ending": "Sep/2026"}
    if (server, tool) == ("filings", "get_transcript_excerpt"):
        return {"status": "unavailable", "reason": "no page"}
    raise AssertionError(f"unexpected tool call: {server}/{tool}")


def _assert_nbis_pack(pack):
    assert pack.status == "REPORTED"
    assert str(pack.quarter_end) == "2026-09-30"
    assert pack.quarter_label == "Q3 2026"
    rev = next(f for f in pack.facts if f.metric == "total_revenue" and f.period == "2026-09-30")
    assert rev.value == 0.9808
    assert rev.source.publisher.startswith("SEC EDGAR")
    assert any(f.metric == "adjusted_ebitda" for f in pack.facts)
    assert not any("no quarterly numbers" in m for m in pack.missing)
    assert any("6-K exhibit 99.1" in m for m in pack.missing)


def test_scout_pack_nbis_latest_path():
    _assert_nbis_pack(collect_evidence("NBIS", _nbis_fake))


def test_scout_pack_nbis_requested_quarter(monkeypatch):
    import mesh.scout as scout_mod
    monkeypatch.setattr(scout_mod, "_resolve_6k_exhibit", lambda cik, acc: EXHIBIT_NAME)
    _assert_nbis_pack(collect_evidence("NBIS", _nbis_fake, quarter="Q3 2026"))


def test_scout_pack_nbis_async():
    async def _async_fake(server, tool, args=None):
        return _nbis_fake(server, tool, args)
    _assert_nbis_pack(asyncio.run(collect_evidence_async("NBIS", _async_fake)))


def test_async_resolve_6k_exhibit(monkeypatch):
    import mesh.async_tools as at

    async def _fake_fetch_json(url, headers=None):
        return {"directory": {"item": [{"name": EXHIBIT_NAME}, {"name": "tm2629571d1_ex99-2.htm"}]}}
    monkeypatch.setattr(at, "fetch_json", _fake_fetch_json)
    assert asyncio.run(at.async_resolve_6k_exhibit(1513845, ACC)) == EXHIBIT_NAME


# --- Analyst: adjusted metrics claim like the GAAP ones --------------------

def test_analyst_adjusted_ebitda_claim():
    parsed = extract_release_facts(EXHIBIT, ticker="NBIS", quarter_end=date(2026, 9, 30),
                                   exhibit_url=EXHIBIT_URL, filing_date="2026-11-12")
    facts = [Fact(id=f["id"], metric=f["metric"], value=f["value"], unit=f["unit"],
                  period=f["period"],
                  source=SourceRef(url=f["url"], publisher=f["publisher"], retrieved_at="2026-11-12T00:00:00Z",
                                   excerpt=f["source_tag"]))
             for f in parsed["facts"]]
    pack = EvidencePack(ticker="NBIS", company_name="Nebius Group N.V.", quarter_label="Q3 2026",
                        quarter_end=date(2026, 9, 30), report_date=date(2026, 11, 12),
                        status="REPORTED", facts=facts, missing=[], consensus=None)
    analysis = analyse(pack)
    texts = [c.text for c in analysis.claims]
    assert any("Revenue YoY growth" in t and "+571" in t for t in texts)
    assert any("Adjusted EBITDA YoY growth" in t for t in texts)
    assert any("Adjusted net income YoY growth" in t for t in texts)
