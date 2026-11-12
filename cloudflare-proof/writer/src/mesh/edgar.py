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

EDGAR_HEADERS = {"User-Agent": UA}

EXHIBIT_991_RE = re.compile(r"ex(?:hibit)?[-_]?99[-_.]?1", re.I)
# Batch 62: some filers name the results press release descriptively
# with no 99.1 shape in the filename at all (CoreWeave's Nov 10
# 8-K carries it as coreweave3q26earningspress.htm — the 8-K text
# itself says it is attached as Exhibit 99.1). Those files are
# still the exhibit, so fall back to press-release-shaped names.
# Order matters: ex99.1-shaped names first (proven), descriptive
# names second; callers try each candidate until one yields text.
PRESS_RELEASE_RE = re.compile(r"press|earnings[-_]?release", re.I)


def exhibit_991_candidates(items) -> list:
    """Exhibit 99.1 filenames from an EDGAR index.json directory
    listing. Filers name it unpredictably (a2026-q3_ex991.htm,
    ex99-1.htm, exhibit991.htm), so match the ex99.1 shape, not
    one literal name; HTML only, never the .txt bundle.
    Batch 62: a filer may instead name the release descriptively
    (coreweave3q26earningspress.htm) — those names match the
    press-release shape below and are tried after the ex99.1
    names. Moved here from mesh/kpi.py (Batch 54): the Orchestrator
    proof vendors edgar.py but not kpi.py (kpi.py pulls the LLM
    chain), and Feature 20's past_reactions needs this matcher
    on the Orchestrator path. kpi.py re-exports it."""
    out = []
    for it in items or []:
        name = (it or {}).get("name", "") if isinstance(it, dict) else ""
        if name and EXHIBIT_991_RE.search(name) and name.lower().endswith((".htm", ".html")):
            out.append(name)
    for it in items or []:
        name = (it or {}).get("name", "") if isinstance(it, dict) else ""
        if (name and name not in out and PRESS_RELEASE_RE.search(name)
                and name.lower().endswith((".htm", ".html"))):
            out.append(name)
    return out

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

# Batch 65: a results 6-K furnishes its earnings release as
# Exhibit 99.1 and says so in the shell ("Filed as Exhibit 99.1
# ... is a press release ... announcing the Company's unaudited
# consolidated financial results for the third quarter ended ...").
# Both halves are required: other 6-Ks furnish non-earnings 99.1s.
_RESULTS_6K_RE = re.compile(r"exhibit\s+99\.1", re.IGNORECASE)
_RESULTS_6K_RESULTS_RE = re.compile(r"financial results", re.IGNORECASE)


def _is_earnings_8k_text(clean_text: str) -> bool:
    """True when a cleaned 8-K head furnishes an earnings release.

    Earnings releases are furnished under Item 2.02 (Results of
    Operations and Financial Condition). The heading is the signal,
    not an exhibit name: some companies inline the release in the
    8-K body (NVDA does — no separate exhibit 99.1 exists), so an
    exhibit-99.1 check alone would miss them.
    """
    return bool(_EARNINGS_ITEM_RE.search(clean_text or ""))


def _is_results_6k_text(clean_text: str) -> bool:
    """True when a cleaned 6-K shell furnishes an earnings release
    as Exhibit 99.1 (Batch 65)."""
    text = clean_text or ""
    return bool(_RESULTS_6K_RE.search(text) and _RESULTS_6K_RESULTS_RE.search(text))


def _filing_index_items(cik: int, accession: str) -> list:
    """Directory items of one filing's index.json (for exhibit
    resolution)."""
    url = (f"https://www.sec.gov/Archives/edgar/data/{cik}/"
           f"{accession.replace('-', '')}/index.json")
    try:
        return (_get_json(url).get("directory", {}) or {}).get("item", []) or []
    except Exception:
        return []


def _resolve_6k_exhibit(cik: int, accession: str) -> str | None:
    """The results press release filename inside a 6-K filing
    (ex99.1-shaped first, descriptive press-release names
    second — same matcher as the KPI leg, Batch 62)."""
    cands = exhibit_991_candidates(_filing_index_items(cik, accession))
    return cands[0] if cands else None


def _find_results_6k(recent: dict, cik: int, ticker: str, company_name: str) -> dict | None:
    """Newest 6-K furnishing an earnings release (Batch 65), with
    its Exhibit 99.1 resolved as the primary document. None when
    no recent 6-K is a results 6-K."""
    sixks = [(i, recent["accessionNumber"][i], recent["primaryDocument"][i])
             for i, form in enumerate(recent["form"]) if form == "6-K"][:_MAX_EARNINGS_CANDIDATES]
    for i, acc, doc in sixks:
        try:
            head = get_filing_text(ticker, acc, doc, max_chars=12000).get("excerpt", "")
        except Exception:
            continue
        if not _is_results_6k_text(head):
            continue
        exhibit = _resolve_6k_exhibit(cik, acc)
        primary = exhibit or doc
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{primary}"
        return {
            "ticker": ticker, "company_name": company_name, "cik": cik,
            "form": "6-K", "filingDate": recent["filingDate"][i],
            "accessionNumber": acc, "primaryDocument": primary, "url": url,
            "filing_kind": "6-K",
            "note": "Most recent 6-K furnishing an earnings release (Exhibit 99.1). "
                    "Foreign private issuer: no 10-Q/8-K, so quarterly figures come "
                    "from the release text, not XBRL — verify the quarter in the document text.",
        }
    return None


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
        # Batch 65: no earnings 8-K — foreign private issuers
        # (Nebius) report on 6-K. Try the results 6-K before
        # falling back to the most recent filing overall.
        sixk = _find_results_6k(recent, facts["cik"], facts["ticker"], facts["company_name"])
        if sixk is not None:
            return sixk
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
