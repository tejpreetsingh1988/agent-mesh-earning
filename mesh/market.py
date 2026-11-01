"""Market data via yfinance — free, unofficial, labelled as such in sources.
yfinance is not an official Yahoo API. Treat its numbers as market context,
never as a replacement for the filing. After-hours moves are NOT available
here — price_reaction reports regular-session closes only, with the window stated.
"""
import datetime

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
    """Closes around report_date. If report_date is empty, use the last
    5 trading days. Returns closes with dates, so the Analyst can compute
    the move and state its window — it does NOT invent an after-hours move.
    """
    t = _ticker(ticker)
    if report_date:
        start = (datetime.date.fromisoformat(report_date) - datetime.timedelta(days=7)).isoformat()
        end = (datetime.date.fromisoformat(report_date) + datetime.timedelta(days=7)).isoformat()
        hist = t.history(start=start, end=end)
    else:
        hist = t.history(period="10d")
    closes = []
    for dt, row in hist.iterrows():
        closes.append({"date": dt.date().isoformat(), "close": round(float(row["Close"]), 2),
                       "open": round(float(row["Open"]), 2), "volume": int(row["Volume"]) if row["Volume"] == row["Volume"] else None})
    return {"ticker": ticker.upper(), "report_date": report_date or None,
            "closes": closes, "window": "Regular-session closes from yfinance (unofficial). After-hours move is NOT in this data — do not claim one from it.",
            "source": "yfinance (unofficial)"}

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
