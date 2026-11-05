"""Recent filings card (Feature 12) — newest 1x 10-K, 3x 10-Q, 5x 8-K
from the SEC EDGAR submissions feed, with document URLs built from
the Archives pattern (never guessed from a different pattern).

Metadata + links only: the card never says what a filing contains,
and an 8-K is listed as an 8-K — never labelled "earnings" here
(the quarter's earnings 8-K is identified by the Scout, not by
this card). The picker is pure; the fetch is async over the shared
worker_http transport, so the Batch 35 retry applies. A failed
fetch returns an error payload and the frontend hides the card.
"""

from .async_tools import _submissions, async_get_company_facts

# Form -> how many of the newest to keep. Selection is by recency
# in the feed, not by interpretation.
FORM_LIMITS = {"10-K": 1, "10-Q": 3, "8-K": 5}


def filing_url(cik: int, accession: str, primary: str) -> str:
    """SEC Archives document URL. The accession's dashes are
    stripped — that is the Archives path convention, not a guess."""
    return (f"https://www.sec.gov/Archives/edgar/data/{cik}/"
            f"{accession.replace('-', '')}/{primary}")


def _at(recent: dict, key: str, i: int) -> str:
    arr = (recent or {}).get(key) or []
    return arr[i] if i < len(arr) else ""


def pick_recent_filings(cik: int, recent: dict) -> dict:
    """Pure: newest 1x 10-K, 3x 10-Q, 5x 8-K from a submissions
    `recent` block (parallel arrays, newest first). Rows carry
    form, filingDate, reportDate, accessionNumber, primaryDocument
    and the built document URL. Unknown forms are skipped; a short
    feed yields short lists, never an error; a row without an
    accession or primary document is skipped."""
    out = {"10-K": [], "10-Q": [], "8-K": []}
    forms = (recent or {}).get("form") or []
    for i, form in enumerate(forms):
        if form not in FORM_LIMITS:
            continue
        if len(out[form]) >= FORM_LIMITS[form]:
            continue
        acc = _at(recent, "accessionNumber", i)
        primary = _at(recent, "primaryDocument", i)
        if not acc or not primary:
            continue
        out[form].append({
            "form": form,
            "filingDate": _at(recent, "filingDate", i),
            "reportDate": _at(recent, "reportDate", i),
            "accessionNumber": acc,
            "primaryDocument": primary,
            "url": filing_url(cik, acc, primary),
        })
        if all(len(out[f]) >= FORM_LIMITS[f] for f in FORM_LIMITS):
            break
    return out


async def fetch_recent_filings_async(ticker: str) -> dict:
    """{ticker, company_name, cik, filings: {10-K, 10-Q, 8-K}} or
    {ticker, error}. Never raises — a failed fetch hides the card
    instead of breaking a briefing."""
    t = (ticker or "").strip().upper()
    try:
        facts = await async_get_company_facts(t)
        if "error" in facts:
            return {"ticker": t, "error": facts["error"]}
        sub = await _submissions(facts["cik_padded"])
        recent = (sub or {}).get("filings", {}).get("recent") or {}
        return {"ticker": facts["ticker"],
                "company_name": facts.get("company_name", ""),
                "cik": facts["cik"],
                "filings": pick_recent_filings(facts["cik"], recent)}
    except Exception as e:  # noqa: BLE001 - hide, never break
        return {"ticker": t, "error": str(e)}
