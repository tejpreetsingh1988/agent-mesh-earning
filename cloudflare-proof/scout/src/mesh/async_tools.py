"""Async mirrors of the sync MCP tools, for the Scout Worker (v2).

Why this module exists: Cloudflare Python Workers cannot do
synchronous urllib (see mesh/worker_http.py), so the sync tool
functions in mesh/edgar.py, mesh/edgar_facts.py, mesh/consensus.py
and mesh/transcript.py all fail in-Worker. These async versions
hit the same URLs and return the same shapes — and wherever the
sync code already isolated a pure parser, it is imported here,
not copied (parse_concept_rows, derive_q4_rows, the Nasdaq /
Alpha Vantage parsers, the transcript candidate/parse helpers).
Only the fetch + small selection logic is mirrored, and each
function names its sync original in its docstring.

The sync originals stay the source of truth for Docker and for
the eval harness; this module is imported only by the Worker
proof (mesh/scout_async.py via async_direct_call) and by tests.
Do not add a tool here without adding its sync twin's parity
case to tests/unit/test_scout_async.py.

Market tools are deliberately thin: they call the sync yfinance
functions directly. On the Worker yfinance is not installed, so
the lazy import raises inside Scout's try blocks and lands in
`missing` — exactly the v1 behaviour. Locally they work as usual.
"""
import asyncio
import os

from . import edgar as edgar_mod
from .consensus import (
    GOOGL_Q3_2026_RANGE,
    _is_googl_q3,
    parse_alpha_vantage_earnings,
    parse_nasdaq_calendar,
)
from .edgar_facts import (
    ALTERNATE_TAGS,
    USER_AGENT as EDGAR_FACTS_UA,
    derive_q4_rows,
    parse_concept_rows,
    pick_latest_tag,
)
from .transcript import (
    UA as TRANSCRIPT_UA,
    candidate_urls,
    parse_transcript_html,
)
from .worker_http import WorkerHTTPError, fetch_json, fetch_text

__all__ = ["async_direct_call"]

_NASDAQ_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}

_TICKERS_CACHE: dict | None = None


async def _tickers() -> dict:
    global _TICKERS_CACHE
    if _TICKERS_CACHE is None:
        _TICKERS_CACHE = await fetch_json(
            "https://www.sec.gov/files/company_tickers.json",
            headers={"User-Agent": edgar_mod.UA})
    return _TICKERS_CACHE


async def async_get_company_facts(ticker: str) -> dict:
    """Async mirror of edgar.get_company_facts."""
    t = ticker.strip().upper()
    for v in (await _tickers()).values():
        if v["ticker"] == t:
            cik = int(v["cik_str"])
            return {"ticker": t, "company_name": v["title"], "cik": cik,
                    "cik_padded": f"{cik:010d}", "source": "SEC EDGAR company_tickers.json"}
    return {"error": f"Ticker {t} not found in SEC EDGAR tickers", "ticker": t}


async def _submissions(cik_padded: str) -> dict:
    return await fetch_json(
        f"https://data.sec.gov/submissions/CIK{cik_padded}.json",
        headers={"User-Agent": edgar_mod.UA})


async def async_list_recent_filings(ticker: str, limit: int = 10) -> dict:
    """Async mirror of edgar.list_recent_filings."""
    facts = await async_get_company_facts(ticker)
    if "error" in facts:
        return facts
    sub = await _submissions(facts["cik_padded"])
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


async def async_get_latest_earnings_filing(ticker: str) -> dict:
    """Async mirror of edgar.get_latest_earnings_filing."""
    facts = await async_get_company_facts(ticker)
    if "error" in facts:
        return facts
    sub = await _submissions(facts["cik_padded"])
    recent = sub["filings"]["recent"]
    idx = None
    for i, form in enumerate(recent["form"]):
        if form == "8-K":
            idx = i
            break
    if idx is None:
        idx = 0
    acc = recent["accessionNumber"][idx]
    doc = recent["primaryDocument"][idx]
    url = f"https://www.sec.gov/Archives/edgar/data/{facts['cik']}/{acc.replace('-', '')}/{doc}"
    return {
        "ticker": facts["ticker"], "company_name": facts["company_name"], "cik": facts["cik"],
        "form": recent["form"][idx], "filingDate": recent["filingDate"][idx],
        "accessionNumber": acc, "primaryDocument": doc, "url": url,
        "note": "8-K is the usual earnings-release filing. Verify the quarter in the document text — do not assume it from the filing date alone.",
    }


async def async_get_filing_text(ticker: str = "", accession: str = "", primary_document: str = "", max_chars: int = 12000) -> dict:
    """Async mirror of edgar.get_filing_text."""
    if not accession or not primary_document:
        latest = await async_get_latest_earnings_filing(ticker) if ticker else {}
        if "error" in latest or not latest:
            return {"error": "Provide ticker, or accession + primaryDocument from get_latest_earnings_filing"}
        accession, primary_document = latest["accessionNumber"], latest["primaryDocument"]
        cik = latest["cik"]
    else:
        facts = await async_get_company_facts(ticker) if ticker else {}
        cik = facts.get("cik") if facts else None
        if cik is None:
            return {"error": "Cannot resolve CIK — provide ticker"}
    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{primary_document}"
    html_text = await fetch_text(url, headers={"User-Agent": edgar_mod.UA})
    clean = edgar_mod._clean_html(html_text)
    return {"url": url, "accessionNumber": accession, "primaryDocument": primary_document,
            "char_count": len(clean), "excerpt": clean[:max_chars],
            "note": "Excerpt only (first 12k chars after the XBRL header). Full document is at url."}


async def _fetch_concept(cik: int, tag: str) -> dict:
    # Both transports decompress gzip themselves (fetch on the
    # Worker, the to_thread urllib path locally), so unlike the
    # sync fetch_concept no manual gzip handling is needed here.
    url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/us-gaap/{tag}.json"
    return await fetch_json(url, headers={"User-Agent": EDGAR_FACTS_UA})


async def async_get_quarterly_facts(cik: int, limit: int = 8) -> dict:
    """Async mirror of edgar_facts.get_quarterly_facts, with the
    same recency-aware tag pick (see pick_latest_tag). Tag
    fetches run concurrently: a ticker can need up to 10 concept
    payloads, and fetching them one by one was the slowest part
    of the Scout Worker. gather preserves tag order, so the
    tie-break (earlier-priority tag stands) still holds."""
    result: dict = {}
    missing: list[str] = []
    for metric, tags in ALTERNATE_TAGS.items():
        async def _one(tag):
            try:
                payload = await _fetch_concept(cik, tag)
                rows = parse_concept_rows(payload, metric)
            except Exception:
                return (tag, [])
            if not rows:
                return (tag, [])
            rows = list(rows)
            seen = {r["period_end"] for r in rows}
            for derived in derive_q4_rows(payload, metric):
                if derived["period_end"] not in seen:
                    rows.append(derived)
            rows.sort(key=lambda r: r["period_end"] or "", reverse=True)
            return (tag, rows)
        candidates = await asyncio.gather(*[_one(tag) for tag in tags])
        picked = pick_latest_tag(candidates)
        if picked:
            tag, rows = picked
            result[metric] = {"tag": tag, "rows": rows[:limit]}
        else:
            missing.append(f"No quarterly-duration 10-Q row for {metric} (tried: {', '.join(tags)})")
    result["missing"] = missing
    return result


async def async_get_filing_facts(ticker: str) -> dict:
    """Async mirror of edgar_facts.get_filing_facts_for_ticker."""
    facts = await async_get_company_facts(ticker)
    if "error" in facts:
        return facts
    quarterly = await async_get_quarterly_facts(facts["cik"])
    out = []
    for metric, data in quarterly.items():
        if metric == "missing":
            continue
        for row in data["rows"]:
            if metric == "gaap_eps":
                value, unit = float(row["value"]), "USD"
            else:
                value, unit = float(row["value"]) / 1e9, "USD_B"
            out.append({
                "id": f"edgar_{metric}_{row['period_end']}" + ("_derived" if row.get("derived") else ""),
                "metric": metric, "value": value, "unit": unit,
                "period": row["period_end"], "source_tag": data["tag"],
                "derived": bool(row.get("derived")),
                "derivation": row.get("derivation", ""),
                "form": row["form"], "filed": row.get("filed"),
            })
    return {"ticker": facts["ticker"], "company_name": facts["company_name"],
            "cik": facts["cik"], "facts": out, "missing": quarterly["missing"]}


async def _fetch_nasdaq_calendar(ticker: str, report_date: str) -> dict:
    """Async mirror of consensus.fetch_nasdaq_calendar."""
    if not report_date:
        return {"ticker": ticker.upper(), "status": "unavailable",
                "source": "Nasdaq calendar", "reason": "No report date supplied for Nasdaq calendar lookup."}
    url = f"https://api.nasdaq.com/api/calendar/earnings?date={report_date}"
    try:
        data = await fetch_json(url, headers=_NASDAQ_HEADERS)
    except Exception as e:
        return {"ticker": ticker.upper(), "status": "unavailable",
                "source": "Nasdaq calendar", "reason": f"Nasdaq calendar request failed: {e}"}
    return parse_nasdaq_calendar(data, ticker)


async def _fetch_alpha_vantage_earnings(ticker: str, quarter: str = "") -> dict:
    """Async mirror of consensus.fetch_alpha_vantage_earnings."""
    key = os.environ.get("ALPHA_VANTAGE_API_KEY", "")
    if not key:
        return {"ticker": ticker.upper(), "status": "unavailable",
                "source": "Alpha Vantage",
                "reason": "No ALPHA_VANTAGE_API_KEY set. Get a free key at alphavantage.co and set it in .env."}
    url = (f"https://www.alphavantage.co/query?function=EARNINGS"
           f"&symbol={ticker.strip().upper()}&apikey={key}")
    try:
        data = await fetch_json(url, headers={"User-Agent": "agent-mesh-earnings/0.1"})
    except Exception as e:
        return {"ticker": ticker.upper(), "status": "unavailable",
                "source": "Alpha Vantage", "reason": f"Alpha Vantage request failed: {e}"}
    if "Note" in data or "Information" in data:
        return {"ticker": ticker.upper(), "status": "unavailable",
                "source": "Alpha Vantage",
                "reason": f"Alpha Vantage rate limit / key issue: {data.get('Note') or data.get('Information')}"}
    return parse_alpha_vantage_earnings(data, ticker, quarter)


async def async_get_consensus(ticker: str, quarter: str = "", report_date: str = "") -> dict:
    """Async mirror of consensus.get_consensus (same chain)."""
    t = ticker.strip().upper()
    date = report_date or ("2026-10-28" if _is_googl_q3(t, quarter) else "")
    if date:
        nasdaq = await _fetch_nasdaq_calendar(t, date)
        if nasdaq.get("status") == "forecast_only":
            return nasdaq
        if nasdaq.get("status") == "available":
            if _is_googl_q3(t, quarter):
                nasdaq["cross_check_range"] = GOOGL_Q3_2026_RANGE
            if os.environ.get("ALPHA_VANTAGE_API_KEY"):
                await asyncio.sleep(1.2)  # Alpha Vantage free tier: 1 request/second
                av = await _fetch_alpha_vantage_earnings(t, quarter)
                if av.get("status") == "available":
                    nasdaq["alpha_vantage_cross_check"] = av
                    nasdaq["basis_note"] = ("Nasdaq reported EPS is GAAP ($2.12 for GOOGL Q3); "
                                            "Alpha Vantage reported EPS is adjusted ($2.87). "
                                            "Compare consensus only to the matching basis.")
            return nasdaq
    live = await _fetch_alpha_vantage_earnings(t, quarter)
    if live.get("status") == "available":
        if _is_googl_q3(t, quarter):
            live["cross_check_range"] = GOOGL_Q3_2026_RANGE
            live["note"] = ("Alpha Vantage is the live tool result. The GOOGL Q3 range is a "
                            "web-verified cross-check, not a second live source.")
        return live
    if _is_googl_q3(t, quarter):
        out = dict(GOOGL_Q3_2026_RANGE)
        out["status"] = "available_range"
        out["live_source"] = "none (Nasdaq fetch failed and no Alpha Vantage key set)"
        out["how_to_enable_live"] = ("Nasdaq calendar needs the report date (2026-10-28 for GOOGL Q3); "
                                     "or set ALPHA_VANTAGE_API_KEY in .env (free key, ~25 calls/day).")
        return out
    return {"ticker": t, "quarter": quarter, "status": "unavailable",
            "reason": ("No live free consensus available for this ticker/quarter. "
                       "Nasdaq calendar needs a report date; Alpha Vantage needs a key."),
            "how_to_enable_live": ("Pass report_date for Nasdaq calendar, or set ALPHA_VANTAGE_API_KEY "
                                   "in .env (free key from alphavantage.co, ~25 calls/day)."),
            "note": "Do not substitute a Yahoo calendar average or a single news article's number as 'the consensus'."}


async def async_fetch_transcript(ticker: str, company_name: str = "", quarter_label: str = "",
                                 report_date: str = "", quarter: str = "") -> dict:
    """Async mirror of transcript.fetch_transcript."""
    label = quarter_label or quarter
    urls = candidate_urls(ticker, company_name, label, report_date)
    if not urls:
        return {"ticker": ticker.upper(), "status": "unavailable",
                "source": "Motley Fool (public transcript page)",
                "reason": "Cannot derive a transcript URL: need a quarter label (e.g. 'Q3 2026') or a report date."}
    last_error = ""
    for url in urls:
        try:
            html_text = await fetch_text(url, headers={"User-Agent": TRANSCRIPT_UA, "Accept": "text/html"})
        except WorkerHTTPError as e:
            last_error = f"HTTP {e.code} for {url}"
            continue
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
            continue
        # Sync version records the final (possibly redirected) URL;
        # fetch does not expose it here, and candidates end with a
        # slash so redirects are not expected to change the slug.
        parsed = parse_transcript_html(html_text, url)
        if parsed.get("status") == "available":
            parsed["ticker"] = ticker.upper()
            parsed["quarter"] = label
            return parsed
        last_error = parsed.get("reason", "page is not a transcript")
    return {"ticker": ticker.upper(), "quarter": label, "status": "unavailable",
            "source": "Motley Fool (public transcript page)",
            "reason": f"No matching Motley Fool transcript page found among candidate URLs (last: {last_error}). "
                      "Transcript may not be published yet, or Fool may use a different slug for this company. "
                      "Briefing continues without a transcript — no quotes are invented."}


async def _market_tool(name: str, *args):
    # Direct sync call, on purpose: on the Worker yfinance is not
    # installed, so the lazy import inside the market function
    # raises before any I/O and Scout records it in `missing`.
    # A to_thread wrapper would be wrong here — Workers have no
    # threads to run it on.
    from . import market
    return getattr(market, name)(*args)


async def async_get_price_reaction(ticker: str, report_date: str = "") -> dict:
    return await _market_tool("get_price_reaction", ticker, report_date)


async def async_get_quarterly_history(ticker: str, quarters: int = 4) -> dict:
    return await _market_tool("get_quarterly_history", ticker, quarters)


async def async_get_company_profile(ticker: str) -> dict:
    return await _market_tool("get_company_profile", ticker)


_TOOLS = {
    "filings": {
        "get_company_facts": async_get_company_facts,
        "get_filing_facts": async_get_filing_facts,
        "get_latest_earnings_filing": async_get_latest_earnings_filing,
        "get_filing_text": async_get_filing_text,
        "get_transcript_excerpt": async_fetch_transcript,
        "list_recent_filings": async_list_recent_filings,
    },
    "market": {
        "get_price_reaction": async_get_price_reaction,
        "get_quarterly_history": async_get_quarterly_history,
        "get_company_profile": async_get_company_profile,
    },
    "estimates_news": {
        "get_consensus_estimates": async_get_consensus,
    },
}


async def async_direct_call(server: str, tool: str, args: dict | None = None) -> dict:
    """Async twin of direct_call: same (server, tool, args) contract."""
    try:
        fn = _TOOLS[server][tool]
    except KeyError:
        raise ValueError(f"Unknown MCP tool: {server}/{tool}") from None
    return await fn(**(args or {}))
