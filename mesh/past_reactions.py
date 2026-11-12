"""Past earnings reactions table (Feature 20) — how the stock's
close moved around each of the last four earnings reports.

Identification reuses the KPI batch's rule (mesh/kpi.py):
for each quarter end, the earnings 8-K is an 8-K filed within
75 days after that quarter end whose index lists an
exhibit-99.1-shaped file. One difference from the KPI batch's
`fetch_release_text_async`, which takes only the single
earliest 8-K in the window: here the candidates are tried in
filing-date order until one carries a 99.1 file, because the
spec's rule is "the 8-K ... whose index lists" one — an
earlier 8-K without a 99.1 (a debt offering, a leadership
change) must not block a later earnings 8-K in the same window.
For the last 2 quarters of a test company the two agree (the
earliest 8-K in the window IS the earnings one); the C1
composition check verifies that on the first live run.

Closes reuse the Batch 28 rule with no new close logic:
`mesh/market.py::reaction_payload` — base = last close on or
before the report date, reaction = first close after it.
A quarter whose earnings 8-K cannot be identified is omitted
(never approximated from a press date or a calendar date).
A quarter with no close after the report date yet shows None
for close_after / change_pct (the UI renders "—"). Fewer
than 2 rows means the card hides (the route still returns
the rows it found).

The table never claims the move was caused by earnings, or
that past reactions predict the next one — it shows closes
around report dates, nothing more.
"""
import asyncio
from datetime import date, timedelta

from .async_tools import _submissions, async_get_company_facts
from .edgar import EDGAR_HEADERS, exhibit_991_candidates
from .market import NASDAQ_HEADERS, NASDAQ_URL, nasdaq_window, parse_nasdaq_closes, reaction_payload
from .worker_http import fetch_json as _afetch_json

WINDOW_DAYS = 75
MAX_QUARTERS = 4


def quarter_ends_from_recent(recent, n=MAX_QUARTERS):
    """Last n 10-Q reportDates from a submissions `recent` block,
    newest first. A 10-Q's reportDate IS its quarter end, so the
    feed itself supplies the quarter ends — the route needs no
    briefing facts. Short feed yields short lists, never an
    error."""
    out = []
    forms = (recent or {}).get("form") or []
    reports = (recent or {}).get("reportDate") or []
    for f, r in zip(forms, reports):
        if f != "10-Q" or not r:
            continue
        try:
            date.fromisoformat(r)
        except ValueError:
            continue
        if r not in out:
            out.append(r)
        if len(out) >= n:
            break
    return out


def earnings_8k_candidates(recent, quarter_end_iso):
    """8-K (filingDate, accession) pairs filed after the quarter
    end and within 75 days, earliest first. Pure; the index
    check happens in the caller. Batch 65: when no 8-K fits,
    fall back to 6-Ks in the same window (foreign private
    issuers furnish results on 6-K)."""
    try:
        qe = date.fromisoformat(quarter_end_iso)
    except (ValueError, TypeError):
        return []
    out = []
    forms = (recent or {}).get("form") or []
    dates = (recent or {}).get("filingDate") or []
    accs = (recent or {}).get("accessionNumber") or []
    for want in ("8-K", "6-K"):
        for f, d, a in zip(forms, dates, accs):
            if f != want or not d or not a:
                continue
            try:
                fd = date.fromisoformat(d)
            except ValueError:
                continue
            if qe < fd <= qe + timedelta(days=WINDOW_DAYS):
                out.append((d, a))
        if out:
            break
    out.sort(key=lambda p: p[0])
    return out


async def _identify_8k(cik, recent, quarter_end, fetch_json=_afetch_json):
    """(filingDate, accession) of the quarter's earnings 8-K, or
    None. Tries the window's 8-Ks earliest-first until one's
    index lists an exhibit-99.1-shaped file."""
    for filing_date, accession in earnings_8k_candidates(recent, quarter_end):
        try:
            index = await fetch_json(
                f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/index.json",
                headers=EDGAR_HEADERS)
        except Exception:
            continue
        items = ((index or {}).get("directory") or {}).get("item") or []
        if exhibit_991_candidates(items):
            return filing_date, accession
    return None


async def _row_for_quarter(ticker, cik, recent, quarter_end, fetch_json=_afetch_json):
    """One table row, or None when the quarter is omitted (no
    identifiable earnings 8-K, or no closes at all)."""
    found = await _identify_8k(cik, recent, quarter_end, fetch_json)
    if not found:
        return None
    report_date, _accession = found
    fromd, tod = nasdaq_window(report_date)
    try:
        body = await fetch_json(
            NASDAQ_URL.format(sym=ticker, fromd=fromd, tod=tod),
            headers=NASDAQ_HEADERS)
    except Exception:
        return None
    closes = parse_nasdaq_closes(body)
    if not closes:
        return None
    payload = reaction_payload(ticker, report_date, closes)
    window = payload.get("closes") or []
    base = None
    reaction = None
    for c in window:
        if c["date"] <= report_date:
            base = c
        elif reaction is None:
            reaction = c
    if base is None:
        return None
    close_before = base["close"]
    close_after = reaction["close"] if reaction else None
    change_pct = (round((close_after - close_before) / close_before * 100, 1)
                  if close_after is not None and close_before else None)
    return {"quarter_end": quarter_end, "report_date": report_date,
            "close_before": close_before, "close_after": close_after,
            "change_pct": change_pct}


async def report_date_for_ticker(ticker, fetch_json=_afetch_json):
    """The latest quarter's earnings 8-K filing date (the
    briefing's report date), or None when no earnings 8-K can
    be identified. Shared by Feature 24's news card, which
    needs the same date the Scout used — the Briefing schema
    does not carry it. Never raises for a bad fetch; only a
    bad ticker raises ValueError."""
    from .history import TICKER_RE
    t = (ticker or "").strip().upper()
    if not TICKER_RE.match(t):
        raise ValueError(f"Invalid ticker for report-date fetch: {ticker!r}")
    try:
        facts = await async_get_company_facts(t)
        if "error" in facts:
            return None
        sub = await _submissions(facts["cik_padded"])
        recent = (sub or {}).get("filings", {}).get("recent") or {}
        quarter_ends = quarter_ends_from_recent(recent, n=1)
        if not quarter_ends:
            return None
        found = await _identify_8k(facts["cik"], recent, quarter_ends[0], fetch_json)
        return found[0] if found else None
    except Exception:
        return None


async def past_reactions_for_ticker(ticker, fetch_json=_afetch_json):
    """{ticker, rows, omitted} for the /past-reactions route.
    Rows newest first, up to 4. `omitted` counts quarters with
    no identifiable earnings 8-K or no closes. Only a bad
    ticker raises ValueError (the route turns it into a 400);
    every fetch failure degrades to an omission, never an
    exception."""
    from .history import TICKER_RE
    t = (ticker or "").strip().upper()
    if not TICKER_RE.match(t):
        raise ValueError(f"Invalid ticker for past-reactions fetch: {ticker!r}")
    facts = await async_get_company_facts(t)
    if "error" in facts:
        return {"ticker": t, "rows": [], "omitted": 0}
    sub = await _submissions(facts["cik_padded"])
    recent = (sub or {}).get("filings", {}).get("recent") or {}
    quarter_ends = quarter_ends_from_recent(recent)
    rows = await asyncio.gather(*[
        _row_for_quarter(t, facts["cik"], recent, qe, fetch_json)
        for qe in quarter_ends])
    kept = [r for r in rows if r is not None]
    return {"ticker": t, "rows": kept, "omitted": len(quarter_ends) - len(kept)}
