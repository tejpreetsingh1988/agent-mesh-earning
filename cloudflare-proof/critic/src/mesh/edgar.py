"""SEC EDGAR client — read-only, free, no key.
SEC requires a descriptive User-Agent. Set EDGAR_USER_AGENT in .env
to something with a real contact, e.g.
agent-mesh-earnings/0.1 (you@example.com)
Default is a placeholder for demo use; do not ship it to production
without replacing the contact.
Rate: EDGAR asks for max 10 req/sec — we make a handful per query,
with no loops, so we stay well under it.
"""
import html as html_lib
import json
import os
import re
import urllib.request
from functools import lru_cache

UA = os.environ.get("EDGAR_USER_AGENT", "agent-mesh-earnings/0.1 (contact@example.com)")

def _get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

def _get_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="ignore")

@lru_cache(maxsize=1)
def _tickers():
    return _get_json("https://www.sec.gov/files/company_tickers.json")

def get_company_facts(ticker: str) -> dict:
    t = ticker.strip().upper()
    for v in _tickers().values():
        if v["ticker"] == t:
            cik = int(v["cik_str"])
            return {"ticker": t, "company_name": v["title"], "cik": cik,
                    "cik_padded": f"{cik:010d}", "source": "SEC EDGAR company_tickers.json"}
    return {"error": f"Ticker {t} not found in SEC EDGAR tickers", "ticker": t}

def _submissions(cik_padded: str) -> dict:
    return _get_json(f"https://data.sec.gov/submissions/CIK{cik_padded}.json")

def list_recent_filings(ticker: str, limit: int = 10) -> dict:
    facts = get_company_facts(ticker)
    if "error" in facts:
        return facts
    sub = _submissions(facts["cik_padded"])
    recent = sub["filings"]["recent"]
    out = []
    for i in range(min(limit, len(recent["form"]))):
        acc = recent["accessionNumber"][i]
        out.append({
            "form": recent["form"][i],
            "filingDate": recent["filingDate"][i],
            "accessionNumber": acc,
            "primaryDocument": recent["primaryDocument"][i],
            "reportDate": recent.get("reportDate", [""] * len(recent["form"]))[i] if "reportDate" in recent else "",
            "url": f"https://www.sec.gov/Archives/edgar/data/{facts['cik']}/{acc.replace('-', '')}/{recent['primaryDocument'][i]}",
        })
    return {"ticker": facts["ticker"], "company_name": facts["company_name"], "cik": facts["cik"], "filings": out}

_EARNINGS_ITEM_RE = re.compile(r"item\s+2\.02", re.IGNORECASE)
_MAX_EARNINGS_CANDIDATES = 6


def _is_earnings_8k_text(clean_text: str) -> bool:
    """True when a cleaned 8-K head furnishes an earnings release.

    Earnings releases are furnished under Item 2.02 (Results of
    Operations and Financial Condition). The heading is the signal,
    not an exhibit name: some companies inline the release in the
    8-K body (NVDA does — no separate exhibit 99.1 exists), so an
    exhibit-99.1 check alone would miss them.
    """
    return bool(_EARNINGS_ITEM_RE.search(clean_text or ""))


def get_latest_earnings_filing(ticker: str) -> dict:
    """Most recent 8-K that furnishes an earnings release (Item 2.02).

    The most recent 8-K is often NOT the earnings release:
    frequent filers file 8-Ks for meetings, debt, and other items
    between quarters. NVDA, Nov 2026: the Sep 3, 2026 8-K is not
    earnings; the Aug 26, 2026 one is — and the old most-recent-8-K
    pick anchored consensus + price reaction to Sep 3, so the
    July briefing carried no consensus even though Nasdaq had
    NVDA's Aug 26 row ($2.22 vs $2.09 forecast). The walk checks
    each recent 8-K's primary document head (first 12k chars) for
    Item 2.02, newest first, and falls back to the most recent
    8-K when none matches — never fail the briefing over
    identification. If no 8-K is recent, fall back to the most
    recent filing overall.
    Returns metadata + a cleaned text excerpt, not a full parse.
    """
    facts = get_company_facts(ticker)
    if "error" in facts:
        return facts
    sub = _submissions(facts["cik_padded"])
    recent = sub["filings"]["recent"]
    eights = [(i, recent["accessionNumber"][i], recent["primaryDocument"][i])
              for i, form in enumerate(recent["form"]) if form == "8-K"][:_MAX_EARNINGS_CANDIDATES]
    idx = None
    for i, acc, doc in eights:
        try:
            head = get_filing_text(ticker, acc, doc, max_chars=12000).get("excerpt", "")
        except Exception:
            continue
        if _is_earnings_8k_text(head):
            idx = i
            break
    if idx is None:
        idx = eights[0][0] if eights else 0
    acc = recent["accessionNumber"][idx]
    doc = recent["primaryDocument"][idx]
    url = f"https://www.sec.gov/Archives/edgar/data/{facts['cik']}/{acc.replace('-', '')}/{doc}"
    return {
        "ticker": facts["ticker"], "company_name": facts["company_name"], "cik": facts["cik"],
        "form": recent["form"][idx], "filingDate": recent["filingDate"][idx],
        "accessionNumber": acc, "primaryDocument": doc, "url": url,
        "note": "Most recent 8-K furnishing an earnings release (Item 2.02). Verify the quarter in the document text — do not assume it from the filing date alone.",
    }

def _clean_html(html_text: str) -> str:
    # Skip the hidden XBRL header block if present
    marker = "UNITED STATES SECURITIES"
    if marker in html_text:
        html_text = html_text[html_text.index(marker):]
    text = re.sub(r"<[^>]+>", " ", html_text)
    text = html_lib.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def get_filing_text(ticker: str = "", accession: str = "", primary_document: str = "", max_chars: int = 12000) -> dict:
    """Fetch a filing document by accession. Caller should pass the
    accession + primaryDocument from get_latest_earnings_filing.
    Ticker is used to resolve the CIK if accession alone is given.
    """
    if not accession or not primary_document:
        latest = get_latest_earnings_filing(ticker) if ticker else {}
        if "error" in latest or not latest:
            return {"error": "Provide ticker, or accession + primaryDocument from get_latest_earnings_filing"}
        accession, primary_document = latest["accessionNumber"], latest["primaryDocument"]
        cik = latest["cik"]
    else:
        facts = get_company_facts(ticker) if ticker else {}
        cik = facts.get("cik") if facts else None
        if cik is None:
            return {"error": "Cannot resolve CIK — provide ticker"}
    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{primary_document}"
    html_text = _get_text(url)
    clean = _clean_html(html_text)
    return {"url": url, "accessionNumber": accession, "primaryDocument": primary_document,
            "char_count": len(clean), "excerpt": clean[:max_chars],
            "note": "Excerpt only (first 12k chars after the XBRL header). Full document is at url."}

def get_transcript_excerpt(ticker: str, quarter: str = "") -> dict:
    # Legacy signature (ticker + quarter label only). The filings-mcp
    # tool now calls mesh.transcript.fetch_transcript directly with
    # company_name + report_date, which is what makes Fool's slug
    # discovery work. This wrapper keeps old callers honest: without
    # a company name it tries ticker-only slugs, and returns
    # unavailable rather than inventing a transcript.
    from .transcript import fetch_transcript
    return fetch_transcript(ticker, company_name="", quarter_label=quarter, report_date="")
