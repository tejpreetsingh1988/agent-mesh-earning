"""Feature 12: recent-filings picker — pure selection from a
submissions `recent` block, plus the async fetch wrapper with
fake transport. No live EDGAR calls here."""
import asyncio

import mesh.filings as fl


def _recent():
    # Interleaved forms, newest first — 3x 10-K, 5x 10-Q, 8x 8-K,
    # plus one 10-K/10-Q/8-K each without a primary document
    # (skipped) and one S-8 (ignored).
    forms = ["8-K", "10-Q", "8-K", "10-K", "10-Q", "8-K", "S-8",
             "10-Q", "8-K", "10-K", "10-Q", "8-K", "10-Q", "8-K",
             "8-K", "10-K", "10-Q", "8-K"]
    n = len(forms)
    return {
        "form": forms,
        "filingDate": [f"2026-0{1 + (i % 9)}-15" for i in range(n)],
        "reportDate": [f"2026-0{1 + (i % 9)}-01" for i in range(n)],
        "accessionNumber": [f"0000789019-26-000{i:03d}" for i in range(n)],
        "primaryDocument": [
            "" if i in (3, 10, 13) else f"doc-{i}.htm" for i in range(n)],
    }


def test_filing_url_strips_accession_dashes():
    assert fl.filing_url(789019, "0000789019-26-000123", "msft-20260930.htm") == (
        "https://www.sec.gov/Archives/edgar/data/789019/"
        "000078901926000123/msft-20260930.htm")


def test_pick_recent_filings_limits_1_3_5():
    out = fl.pick_recent_filings(789019, _recent())
    assert [r["form"] for r in out["10-K"]] == ["10-K"]
    assert len(out["10-K"]) == 1
    assert len(out["10-Q"]) == 3
    assert len(out["8-K"]) == 5
    # Newest first: the first 10-K in the feed is index 3, which
    # has no primary document — so the kept one is index 9.
    assert out["10-K"][0]["accessionNumber"] == "0000789019-26-000009"
    assert out["10-K"][0]["url"].endswith(
        "/000078901926000009/doc-9.htm")
    # The S-8 never appears; rows carry both dates.
    assert all(r["filingDate"] and r["reportDate"]
               for rows in out.values() for r in rows)


def test_pick_recent_filings_short_feed():
    recent = {"form": ["10-Q", "8-K"],
              "filingDate": ["2026-01-15", "2026-01-10"],
              "reportDate": ["2025-12-31", ""],
              "accessionNumber": ["0000789019-26-000001",
                                  "0000789019-26-000002"],
              "primaryDocument": ["q.htm", "k.htm"]}
    out = fl.pick_recent_filings(789019, recent)
    assert out["10-K"] == [] and len(out["10-Q"]) == 1 and len(out["8-K"]) == 1


def test_pick_recent_filings_empty():
    assert fl.pick_recent_filings(789019, {}) == {
        "10-K": [], "10-Q": [], "8-K": []}
    assert fl.pick_recent_filings(789019, {"form": []}) == {
        "10-K": [], "10-Q": [], "8-K": []}


def test_fetch_recent_filings_async_uses_picker(monkeypatch):
    async def fake_company_facts(ticker):
        return {"ticker": ticker, "company_name": "Microsoft Corporation",
                "cik": 789019, "cik_padded": "0000789019"}

    async def fake_submissions(padded):
        assert padded == "0000789019"
        return {"filings": {"recent": _recent()}}

    monkeypatch.setattr(fl, "async_get_company_facts", fake_company_facts)
    monkeypatch.setattr(fl, "_submissions", fake_submissions)
    out = asyncio.run(fl.fetch_recent_filings_async("msft"))
    assert out["ticker"] == "MSFT"
    assert len(out["filings"]["10-K"]) == 1
    assert len(out["filings"]["10-Q"]) == 3
    assert len(out["filings"]["8-K"]) == 5


def test_fetch_recent_filings_async_never_raises(monkeypatch):
    async def fake_company_facts(ticker):
        raise RuntimeError("network down")

    monkeypatch.setattr(fl, "async_get_company_facts", fake_company_facts)
    out = asyncio.run(fl.fetch_recent_filings_async("MSFT"))
    assert out["ticker"] == "MSFT" and "error" in out
