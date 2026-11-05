"""Dividend card data (Feature 14) — last 4 dividends + trailing yield.

Pure selection/arithmetic plus one async fetcher, reusing the
history module's Nasdaq helpers (`_money`, `_parse_date`,
`NASDAQ_HEADERS`) and its dividends endpoint, which was probed
live 2026-11-05: `GET /api/quote/{T}/dividends?assetclass=stocks`
answers `{data: {dividends: {rows: [{exOrEffDate, type, amount,
declarationDate, recordDate, paymentDate, currency}]}}}`.
Rows carry MM/DD/YYYY dates; only Cash-type dividends count.

Rules (from the spec): "last 4" means the 4 most recent
dividends with ex-date <= today, in ex-date order. A declared
future ex-date row is shown separately as the next ex-date and
is never counted in the trailing sum. Yield = (sum of those 4
amounts) / last close * 100, to 1 decimal. If any of the 4
amounts is missing/unparseable, or the closes fetch fails, the
yield hides but the dated rows still show. A special/irregular
dividend is included in the sum with no special label, and the
card never annualises a single dividend. Companies with no
dividends hide the card entirely (the route returns empty rows).

The route (`GET /dividends`) and the frontend card land in the
follow-up batch — this module is the data leg, built first so it
can be unit-tested and live-probed without touching the
Orchestrator's worker_main (Batch 43's file, unpushed).
"""
import asyncio
from datetime import date

from .history import _money, _parse_date, NASDAQ_HEADERS
from .worker_http import fetch_json as _afetch_json


def select_dividends(rows, today=None):
    """Split raw Nasdaq dividend rows into (last4, next_declared).

    last4: up to 4 Cash dividends with ex-date <= today, most
    recent first, each as {ex_date (ISO), amount (float),
    pay_date (ISO or "")}. next_declared: the earliest Cash
    dividend with ex-date > today, same shape, or None. Rows
    with an unparseable ex-date or amount are dropped; non-Cash
    rows are ignored.
    """
    today = today or date.today()
    past, future = [], []
    for row in rows or []:
        if not isinstance(row, dict) or row.get("type") != "Cash":
            continue
        ex = _parse_date(row.get("exOrEffDate"))
        amount = _money(row.get("amount"))
        if ex is None or amount is None:
            continue
        item = {"ex_date": ex.isoformat(), "amount": amount,
                "pay_date": (_parse_date(row.get("paymentDate")) or date.min).isoformat()
                if _parse_date(row.get("paymentDate")) else ""}
        (past if ex <= today else future).append((ex, item))
    past.sort(key=lambda p: p[0], reverse=True)
    future.sort(key=lambda p: p[0])
    last4 = [item for _, item in past[:4]]
    next_declared = future[0][1] if future else None
    return last4, next_declared


def trailing_yield(last4, last_close):
    """(sum of the last-4 amounts) / last close * 100, 1 decimal.

    Returns None when there is no close, no amounts, or any amount
    is missing — the yield line hides, the rows still show.
    """
    if not last4 or last_close is None or last_close <= 0:
        return None
    amounts = [it.get("amount") for it in last4]
    if any(a is None for a in amounts):
        return None
    return round(sum(amounts) / last_close * 100, 1)


async def dividends_for_ticker(ticker, fetch_json=_afetch_json, today=None):
    """One dividend-card payload for the /dividends route.

    Fetches the Nasdaq dividends rows and the recent closes (for
    the last close) in parallel; either failing degrades to its
    hiding state, never an exception — only a bad ticker raises
    ValueError (the route turns it into a 400).
    """
    from .history import TICKER_RE
    t = (ticker or "").strip().upper()
    if not TICKER_RE.match(t):
        raise ValueError(f"Invalid ticker for dividends fetch: {ticker!r}")
    base = f"https://api.nasdaq.com/api/quote/{t}"

    async def _rows():
        try:
            body = await fetch_json(f"{base}/dividends?assetclass=stocks",
                                    headers=NASDAQ_HEADERS)
            return (((body or {}).get("data") or {}).get("dividends") or {}).get("rows") or []
        except Exception:
            return None

    async def _last_close():
        try:
            end = today or date.today()
            # A 60-day window is plenty for the most recent close;
            # the endpoint caps at 9999 rows.
            from datetime import timedelta
            start = end - timedelta(days=60)
            body = await fetch_json(
                f"{base}/historical?assetclass=stocks"
                f"&fromdate={start.isoformat()}&todate={end.isoformat()}&limit=9999",
                headers=NASDAQ_HEADERS)
            rows = (((body or {}).get("data") or {}).get("tradesTable") or {}).get("rows") or []
            closes = [_money(r.get("close")) for r in rows if isinstance(r, dict)]
            closes = [c for c in closes if c is not None]
            return closes[-1] if closes else None
        except Exception:
            return None

    rows, last_close = await asyncio.gather(_rows(), _last_close())
    if rows is None:
        return {"ticker": t, "rows": [], "next_ex_date": None,
                "trailing_yield": None, "last_close": None}
    last4, next_declared = select_dividends(rows, today)
    return {"ticker": t, "rows": last4, "next_ex_date": next_declared,
            "trailing_yield": trailing_yield(last4, last_close),
            "last_close": last_close}
