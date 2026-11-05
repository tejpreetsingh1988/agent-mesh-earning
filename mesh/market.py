"""Market data: price reaction via Nasdaq daily closes (free, no key),
plus yfinance profile/history (Docker-only, not in the briefing path).
Nasdaq closes are UNADJUSTED regular-session closes — a split or large
dividend between the two days can distort the move, and daily closes
cannot show the after-hours move. Both caveats are labelled in the
payload window string and in the Analyst's claim text.

Batch 28 flip (Nov 4, 2026): Stooq was the first choice, but it
serves nothing to automated clients — VM curl times out, a text
fetch fails with a network error, and a real browser tab renders
blank with no CSV. Nasdaq's historical endpoint serves the same
data class (daily closes, trading days only) as JSON, proven by a
live VM probe the same day (11 GOOGL rows, Oct 20–Nov 3, 2026).
The parser, window, payload, Analyst and Critic code are
source-agnostic and did not change — only the fetcher and the
source label did.
"""
import datetime
import json
import urllib.request

NASDAQ_URL = ("https://api.nasdaq.com/api/quote/{sym}/historical"
              "?assetclass=stocks&fromdate={fromd}&todate={tod}&limit=9999")
NASDAQ_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}


def _money(text) -> float | None:
    """Nasdaq '$324.89' / '63,109,030' strings -> float, None when unparseable."""
    if text is None:
        return None
    try:
        return float(str(text).replace("$", "").replace(",", "").strip())
    except ValueError:
        return None


def _volume(text):
    """Nasdaq '63,109,030' strings -> int, None when unparseable."""
    if text is None:
        return None
    try:
        return int(float(str(text).replace(",", "").strip()))
    except ValueError:
        return None


def parse_nasdaq_closes(data: dict) -> list[dict]:
    """Nasdaq tradesTable rows -> ascending [{date ISO, close, open, volume}].
    Real rows are newest-first with MM/DD/YYYY dates and '$'/comma
    strings; bad rows skipped, never fatal."""
    rows = (((data or {}).get("data") or {}).get("tradesTable") or {}).get("rows") or []
    out = []
    for row in rows:
        try:
            d = datetime.datetime.strptime((row.get("date") or "").strip(), "%m/%d/%Y").date().isoformat()
            close = _money(row.get("close"))
            if close is None or close != close:  # NaN guard
                continue
        except (ValueError, TypeError, AttributeError):
            continue
        open_ = _money(row.get("open"))
        out.append({"date": d, "close": round(close, 2),
                    "open": round(open_, 2) if open_ is not None else None,
                    "volume": _volume(row.get("volume"))})
    out.sort(key=lambda r: r["date"])
    return out


def nasdaq_window(report_date: str = "") -> tuple:
    """(fromdate, todate) covering the reaction window: 60 days
    before through 30 days after the report date, so the base
    (last close on or before) and reaction (first close after)
    plus trim context are always covered. No report date means
    the last 90 days to today."""
    try:
        ref = datetime.date.fromisoformat((report_date or "")[:10])
    except ValueError:
        ref = datetime.date.today()
    return ((ref - datetime.timedelta(days=60)).isoformat(),
            (ref + datetime.timedelta(days=30)).isoformat())


def _select_window(closes: list[dict], report_date: str):
    """(base, reaction, window_rows) for a closes list. Base = last
    close on or before report_date; reaction = first close after it
    (the row after base in sorted order, by construction). Window =
    up to 5 rows before base through 5 rows after reaction — context
    for the card, not the full history (a full history would
    bloat the pack through four Worker calls). Without a report
    date, the last 11 rows."""
    if not closes:
        return None, None, []
    ordered = sorted(closes, key=lambda c: c["date"])
    if not report_date:
        return None, None, ordered[-11:]
    base_idx = None
    for i, c in enumerate(ordered):
        if c["date"] <= report_date:
            base_idx = i
        else:
            break
    if base_idx is None:
        return None, None, ordered[-11:]
    react_idx = base_idx + 1 if base_idx + 1 < len(ordered) else None
    lo = max(0, base_idx - 5)
    hi = min(len(ordered), (react_idx + 6) if react_idx is not None else base_idx + 1)
    return ordered[base_idx], (ordered[react_idx] if react_idx is not None else None), ordered[lo:hi]


def reaction_payload(ticker: str, report_date: str, closes: list[dict]) -> dict:
    """The dict shape the Analyst and Critic consume: windowed
    closes + a window string carrying both caveats (unadjusted,
    no after-hours)."""
    base, reaction, window = _select_window(closes, report_date or "")
    return {"ticker": ticker.upper(), "report_date": report_date or None,
            "closes": window,
            "window": "Regular-session closes from Nasdaq (free, unadjusted — a split or large dividend between the two days can distort the move). Daily closes cannot show the after-hours move — do not claim one from this data.",
            "source": "Nasdaq (free)"}

def _ticker(ticker: str):
    import yfinance as yf
    return yf.Ticker(ticker.strip().upper())

def get_company_profile(ticker: str) -> dict:
    t = _ticker(ticker)
    try:
        info = t.info or {}
    except Exception as e:
        return {"ticker": ticker.upper(), "error": f"yfinance info failed: {e}", "source": "yfinance (unofficial)"}
    return {"ticker": ticker.upper(), "company_name": info.get("longName"),
            "sector": info.get("sector"), "industry": info.get("industry"),
            "market_cap": info.get("marketCap"), "source": "yfinance (unofficial)"}

def get_price_reaction(ticker: str, report_date: str = "") -> dict:
    """Closes around report_date from Nasdaq historical (one JSON
    call, free, no key). The Analyst computes the move from the
    window's base (last close on or before report_date) and
    reaction (first close after it) and states the window — it
    does NOT invent an after-hours move. A fetch failure returns
    an error dict, never an exception, so Scout records it in
    `missing` and the briefing continues without a market section
    (as today)."""
    fromd, tod = nasdaq_window(report_date)
    req = urllib.request.Request(
        NASDAQ_URL.format(sym=ticker.strip().upper(), fromd=fromd, tod=tod),
        headers=NASDAQ_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as e:
        return {"ticker": ticker.upper(), "error": f"Nasdaq fetch failed: {e}", "source": "Nasdaq (free)"}
    closes = parse_nasdaq_closes(data)
    if not closes:
        return {"ticker": ticker.upper(), "error": "Nasdaq returned no parseable closes", "source": "Nasdaq (free)"}
    return reaction_payload(ticker, report_date, closes)

def get_quarterly_history(ticker: str, quarters: int = 4) -> dict:
    t = _ticker(ticker)
    try:
        q = t.quarterly_financials
    except Exception as e:
        return {"ticker": ticker.upper(), "error": f"yfinance quarterly_financials failed: {e}"}
    out = []
    try:
        cols = list(q.columns)[:quarters]
        for c in cols:
            col = q[c]
            out.append({"period_end": str(c.date()) if hasattr(c, "date") else str(c),
                        "total_revenue": float(col.get("Total Revenue")) if col.get("Total Revenue") == col.get("Total Revenue") else None,
                        "operating_income": float(col.get("Operating Income")) if col.get("Operating Income") == col.get("Operating Income") else None})
    except Exception as e:
        return {"ticker": ticker.upper(), "error": f"quarterly parse failed: {e}", "raw_columns": str(list(q.columns)[:quarters])}
    return {"ticker": ticker.upper(), "quarters": out, "source": "yfinance quarterly_financials (unofficial)"}
