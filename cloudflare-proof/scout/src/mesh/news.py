"""Estimates + news via yfinance — with honest limits.
Consensus EPS/revenue from free sources varies by vendor (see ARCHITECTURE
Section 7.3). get_consensus_estimates is now wired to Alpha Vantage
(see mesh/consensus.py): live EPS when ALPHA_VANTAGE_API_KEY is set,
otherwise a labelled GOOGL Q3 2026 range only, and 'unavailable' for
other tickers/quarters. The calendar estimates from yfinance are
returned separately, labelled by source, so the Critic can see they
are estimates, not actuals.
"""
def _ticker(ticker: str):
    import yfinance as yf
    return yf.Ticker(ticker.strip().upper())

def get_consensus_estimates(ticker: str, quarter: str = "", report_date: str = "") -> dict:
    # Wired 2026-10-29: Nasdaq keyless first, Alpha Vantage second (key),
    # GOOGL Q3 2026 range fallback. See mesh/consensus.py for limits.
    from mesh.consensus import get_consensus
    return get_consensus(ticker, quarter, report_date)

def get_earnings_calendar(ticker: str) -> dict:
    t = _ticker(ticker)
    try:
        cal = t.calendar or {}
    except Exception as e:
        return {"ticker": ticker.upper(), "error": f"yfinance calendar failed: {e}"}
    # Convert dates to ISO strings for JSON
    out = {}
    for k, v in cal.items():
        if isinstance(v, list):
            out[k] = [str(x) for x in v]
        else:
            out[k] = str(v)
    return {"ticker": ticker.upper(), "calendar": out, "source": "yfinance calendar (unofficial, estimates — not actuals)"}

def get_recent_news(ticker: str, days: int = 3) -> dict:
    t = _ticker(ticker)
    try:
        news = t.news or []
    except Exception as e:
        return {"ticker": ticker.upper(), "error": f"yfinance news failed: {e}"}
    out = []
    for n in news[:10]:
        content = n.get("content", {}) if isinstance(n, dict) else {}
        provider = content.get("provider", {}) if isinstance(content, dict) else {}
        out.append({"title": content.get("title") or n.get("title"),
                    "publisher": provider.get("displayName") if isinstance(provider, dict) else provider,
                    "url": content.get("canonicalUrl", {}).get("url") if isinstance(content.get("canonicalUrl"), dict) else None,
                    "published": str(content.get("pubDate") or content.get("displayTime") or "")})
    return {"ticker": ticker.upper(), "news": out,
            "note": "News is context only, never a numbers source. If a number appears only in news, Scout marks it unverified.",
            "source": "yfinance news (unofficial)"}
