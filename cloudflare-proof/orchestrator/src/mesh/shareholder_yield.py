"""Shareholder yield (Feature 15) — (buybacks + dividends) / market cap.

Pure formula + one async assembler over existing paths only
(no new source). Inputs:
- Buybacks: trailing 4 quarters from the history series
  (`buybacks` metric, discrete quarterly values, unit USD —
  raw dollars, probed live 2026-11-05).
- Dividends total: sum of the last 4 per-share dividends
  (Feature 14's `dividends_for_ticker`) x latest shares
  outstanding. The latest share count is used for all four
  quarters — an approximation, labelled on the card.
- Market cap: last Nasdaq close x latest shares outstanding
  (the `shares_outstanding` history series, unit `shares` —
  raw share counts, probed live 2026-11-05). This is close x
  latest reported share count, labelled as computed — never
  presented as an official market-cap figure.

If any input is missing (no buyback series, fewer than 4
buyback quarters, fewer than 4 dividend rows, no shares
series, no close) or a series arrives in an unexpected unit,
the whole payload is None — a partial yield is never shown.
The route (`GET /shareholder-yield`) and the frontend card
land in the follow-up batch.
"""
import asyncio

from .dividends import dividends_for_ticker
from .history import history_for_ticker

APPROXIMATION_NOTE = ("Dividends total uses the latest share count "
                      "for all four quarters — an approximation.")


def trailing_sum(series, n=4):
    """Sum of the last n numeric values in a history series.

    The series is sorted ascending by period_end. Returns None
    when fewer than n numeric values exist — the trailing window
    is exactly n quarters.
    """
    values = [p.get("value") for p in (series or [])
              if isinstance(p, dict) and isinstance(p.get("value"), (int, float))]
    if len(values) < n:
        return None
    return sum(values[-n:])


def latest_value(series):
    """Most recent value in a history series, or None."""
    values = [p.get("value") for p in (series or [])
              if isinstance(p, dict) and isinstance(p.get("value"), (int, float))]
    return values[-1] if values else None


def shareholder_yield(buybacks_usd, dividends_usd, market_cap_usd):
    """(buybacks + dividends) / market cap * 100, 1 decimal.

    None when any input is missing or the market cap is not
    positive — the card hides instead of showing a partial
    ratio.
    """
    if (buybacks_usd is None or dividends_usd is None
            or market_cap_usd is None or market_cap_usd <= 0):
        return None
    return round((buybacks_usd + dividends_usd) / market_cap_usd * 100, 1)


async def shareholder_yield_for_ticker(ticker, history_fetch=history_for_ticker,
                                       dividends_fetch=dividends_for_ticker,
                                       today=None):
    """One shareholder-yield payload for the /shareholder-yield route.

    Fetches the buybacks + shares series and the dividend payload
    in parallel; any missing input degrades to None (hide the
    card), never an exception — only a bad ticker raises
    ValueError (the route turns it into a 400).
    """
    from .history import TICKER_RE
    t = (ticker or "").strip().upper()
    if not TICKER_RE.match(t):
        raise ValueError(f"Invalid ticker for shareholder-yield fetch: {ticker!r}")
    buybacks, shares, divs = await asyncio.gather(
        history_fetch(t, "buybacks"),
        history_fetch(t, "shares_outstanding"),
        dividends_fetch(t, today=today),
    )
    if (buybacks or {}).get("unit") != "USD" or (shares or {}).get("unit") != "shares":
        return None
    buybacks_usd = trailing_sum((buybacks or {}).get("series"))
    shares_latest = latest_value((shares or {}).get("series"))
    rows = (divs or {}).get("rows") or []
    last_close = (divs or {}).get("last_close")
    if (buybacks_usd is None or shares_latest is None or len(rows) < 4
            or last_close is None):
        return None
    dividends_usd = sum(r["amount"] for r in rows[:4]) * shares_latest
    market_cap_usd = last_close * shares_latest
    y = shareholder_yield(buybacks_usd, dividends_usd, market_cap_usd)
    if y is None:
        return None
    return {"ticker": t, "buybacks_trailing_usd": buybacks_usd,
            "dividends_trailing_usd": dividends_usd,
            "market_cap_usd": market_cap_usd,
            "shareholder_yield": y,
            "shares_outstanding": shares_latest,
            "last_close": last_close,
            "approximation_note": APPROXIMATION_NOTE}
