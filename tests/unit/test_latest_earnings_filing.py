"""Latest earnings filing: Item 2.02 walk (Nov 4, 2026 fix).

The most recent 8-K is often NOT the earnings release. NVDA,
Nov 2026: the Sep 3, 2026 8-K is not earnings; the Aug 26, 2026
one is — and the old most-recent-8-K pick anchored the July
briefing's consensus + price reaction to Sep 3, losing a real
consensus (Nasdaq Aug 26 row: $2.22 vs $2.09 forecast). The
walk checks each recent 8-K's primary document head for Item
2.02, newest first, and falls back to the most recent 8-K when
none matches. The signal is the Item 2.02 heading, not an
exhibit name: NVDA inlines the release in the 8-K body (no
separate exhibit 99.1 exists).
"""

import asyncio

from mesh import async_tools, edgar

_TICKERS = {"NVDA": {"ticker": "NVDA", "cik_str": "1045810", "title": "NVIDIA CORP"}}


def _subs():
    forms = ["8-K", "8-K", "10-Q", "8-K"]
    dates = ["2026-09-03", "2026-08-26", "2026-08-26", "2026-07-02"]
    accs = ["0001045810-26-000078", "0001045810-26-000073",
            "0001045810-26-000072", "0001045810-26-000060"]
    docs = ["nvda-20260902.htm", "nvda-20260826.htm", "nvda-2026q2.htm", "nvda-20260628.htm"]
    return {"filings": {"recent": {"form": forms, "filingDate": dates,
                                   "accessionNumber": accs, "primaryDocument": docs,
                                   "reportDate": dates}}}


_HEADS = {
    "0001045810-26-000078": "UNITED STATES SECURITIES ... Item 1.01 Entry into a Material Definitive Agreement ...",
    "0001045810-26-000073": "UNITED STATES SECURITIES ... Item 2.02 Results of Operations and Financial Condition ... NVIDIA reports revenue ...",
    "0001045810-26-000060": "UNITED STATES SECURITIES ... Item 5.02 Departure of Directors ...",
}


def _fake_tickers():
    return _TICKERS


def test_picks_item_202_filing_not_most_recent_8k(monkeypatch):
    # Patch _tickers itself (not _get_json + cache_clear): the
    # lru_cache would otherwise keep the fake NVDA-only tickers
    # for later tests in the same process and break GOOGL lookups.
    monkeypatch.setattr(edgar, "_tickers", _fake_tickers)
    monkeypatch.setattr(edgar, "_get_json", lambda url: _subs())
    monkeypatch.setattr(edgar, "get_filing_text",
                        lambda ticker, acc, doc, max_chars=12000: {"excerpt": _HEADS[acc]})
    f = edgar.get_latest_earnings_filing("NVDA")
    assert f["filingDate"] == "2026-08-26"
    assert f["accessionNumber"] == "0001045810-26-000073"


def test_falls_back_to_most_recent_8k(monkeypatch):
    monkeypatch.setattr(edgar, "_tickers", _fake_tickers)
    monkeypatch.setattr(edgar, "_get_json", lambda url: _subs())
    monkeypatch.setattr(edgar, "get_filing_text",
                        lambda ticker, acc, doc, max_chars=12000: {"excerpt": "no earnings item here"})
    f = edgar.get_latest_earnings_filing("NVDA")
    assert f["filingDate"] == "2026-09-03"
    assert f["accessionNumber"] == "0001045810-26-000078"


def test_async_picks_item_202_filing(monkeypatch):
    async def fake_tickers():
        return _TICKERS

    async def fake_subs(cik_padded):
        return _subs()

    async def fake_text(ticker="", accession="", primary_document="", max_chars=12000):
        return {"excerpt": _HEADS[accession]}

    monkeypatch.setattr(async_tools, "_tickers", fake_tickers)
    monkeypatch.setattr(async_tools, "_submissions", fake_subs)
    monkeypatch.setattr(async_tools, "async_get_filing_text", fake_text)
    f = asyncio.run(async_tools.async_get_latest_earnings_filing("NVDA"))
    assert f["filingDate"] == "2026-08-26"
    assert f["accessionNumber"] == "0001045810-26-000073"
