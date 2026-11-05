"""Day 2 tests — live-source smoke tests + TestClient dispatch.
These hit live EDGAR / Yahoo, so they are slower than Day 1 tests and
assert structure, not a frozen quarter (except the GOOGL CIK, which is stable).
"""
import pathlib
from fastapi.testclient import TestClient
from mesh import edgar, market, news
from mcp_servers.filings.main import app as filings_app
from mcp_servers.market.main import app as market_app
from mcp_servers.estimates_news.main import app as news_app

def test_edgar_googl_cik():
    f = edgar.get_company_facts("GOOGL")
    assert f["cik"] == 1652044
    assert f["company_name"] == "Alphabet Inc."

def test_edgar_latest_filing_is_8k_with_url():
    f = edgar.get_latest_earnings_filing("GOOGL")
    assert f["form"] == "8-K"
    assert f["accessionNumber"]
    assert f["url"].startswith("https://www.sec.gov/Archives/")
    assert f["filingDate"] >= "2026-10-28"

def test_edgar_filing_text_contains_alphabet():
    latest = edgar.get_latest_earnings_filing("GOOGL")
    txt = edgar.get_filing_text(ticker="GOOGL", accession=latest["accessionNumber"], primary_document=latest["primaryDocument"], max_chars=8000)
    assert txt["char_count"] > 1000
    assert "Alphabet" in txt["excerpt"] or "alphabet" in txt["excerpt"].lower()

def test_market_profile():
    p = market.get_company_profile("GOOGL")
    assert p["company_name"] == "Alphabet Inc."
    assert p["market_cap"] and p["market_cap"] > 0

def test_market_price_reaction_has_closes(monkeypatch):
    # Fake the Nasdaq JSON fetch (Batch 28 flip: Stooq serves
    # nothing to automated clients, so the live shape is verified
    # by the VM curl probe + post-deploy briefing checks, not by
    # the suite). The parser + window logic are unit-tested in
    # test_nasdaq_reaction.py.
    import json
    import urllib.request

    payload = {"data": {"tradesTable": {"rows": [
        {"date": "10/29/2026", "close": "$295.00", "volume": "1,000,000", "open": "$300.00"},
        {"date": "10/28/2026", "close": "$324.89", "volume": "900,000", "open": "$320.00"},
        {"date": "10/27/2026", "close": "$324.89", "volume": "800,000", "open": "$320.00"},
    ]}}}

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps(payload).encode()

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: FakeResp())
    r = market.get_price_reaction("GOOGL", report_date="2026-10-28")
    assert r["closes"]
    dates = [c["date"] for c in r["closes"]]
    assert "2026-10-28" in dates and "2026-10-29" in dates
    assert r["source"] == "Nasdaq (free)"

def test_news_calendar_and_consensus_honesty():
    cal = news.get_earnings_calendar("GOOGL")
    assert "calendar" in cal or "error" in cal
    # Without an Alpha Vantage key, GOOGL Q3 2026 returns the labelled range,
    # other tickers return unavailable — never a silent single number.
    cons = news.get_consensus_estimates("GOOGL", quarter="Q3 2026")
    assert cons["status"] in ("available", "available_range")
    if cons["status"] == "available_range":
        assert cons["eps_estimate_low"] == 2.94 and cons["eps_estimate_high"] == 3.02
    assert news.get_consensus_estimates("MSFT", quarter="Q3 2026")["status"] == "unavailable"

def test_mcp_http_dispatch():
    c = TestClient(filings_app)
    assert c.get("/health").json()["status"] == "ok"
    r = c.post("/tools/call", json={"tool": "get_company_facts", "args": {"ticker": "GOOGL"}})
    assert r.status_code == 200
    assert r.json()["result"]["cik"] == 1652044
    m = TestClient(market_app)
    r = m.post("/tools/call", json={"tool": "get_company_profile", "args": {"ticker": "GOOGL"}})
    assert r.status_code == 200
    n = TestClient(news_app)
    r = n.post("/tools/call", json={"tool": "get_consensus_estimates", "args": {"ticker": "GOOGL", "quarter": "Q3 2026"}})
    assert r.json()["result"]["status"] in ("available", "available_range")
