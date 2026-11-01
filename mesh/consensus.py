"""Free consensus estimates — Nasdaq keyless first, Alpha Vantage second, range fallback.

Honest limits, carried from ARCHITECTURE Section 7.3:
- No free source is LSEG / FactSet / Bloomberg.
- Nasdaq calendar (api.nasdaq.com/api/calendar/earnings?date=YYYY-MM-DD)
  is keyless and, verified 2026-10-29 for 2026-10-28, gives Consensus EPS
  Forecast + # of estimates + reported EPS + % surprise, with an asOf
  date. It gives NO revenue consensus, NO last-year EPS, and NO
  before/after-market flag (GOOGL time was "time-not-supplied"). It is
  an undocumented public endpoint, not a licensed feed — it can change
  or break, so the code falls through to the next source on any failure.
- Alpha Vantage gives ONE EPS estimate per past quarter (estimatedEPS)
  with reportedEPS and surprise. It does NOT give revenue consensus,
  analyst count, or an as-of date, and it does not say whether its
  estimate is GAAP or adjusted. The Critic must label it "Alpha Vantage
  EPS estimate (basis unstated)" and must NOT compare it silently to
  GAAP EPS. It requires a free API key (25 calls/day).
- Yahoo Finance calendar averages are deliberately NOT used here: for
  GOOGL Q3 2026 they gave $3.33 / $142.8B, which does not line up with
  the Q3 consensus from Nasdaq / MarketBeat / StockInvest, and the
  wrong quarter is easy to pick up.
"""
import json
import os
import urllib.request

# Web-verified range for the worked example only (GOOGL, quarter ended
# 2026-09-30, reported 2026-10-28). Sources checked 2026-10-28/29:
# Nasdaq calendar 2026-10-28: EPS forecast $2.94, 14 estimates, reported $2.12.
# MarketBeat compare table: EPS $3.02, revenue $127.96B.
# StockInvest GOOGL earnings page: EPS $2.97, revenue $127.962B.
# Other press coverage cited revenue ~$128.2B. This range is NOT a live
# API result and must never be used for another ticker or quarter.
GOOGL_Q3_2026_RANGE = {
    "ticker": "GOOGL",
    "quarter": "Q3 2026",
    "fiscal_date_ending": "2026-09-30",
    "reported_date": "2026-10-28",
    "eps_estimate_low": 2.94,
    "eps_estimate_high": 3.02,
    "eps_estimate_range": "2.94-3.02",
    "revenue_estimate_low_b": 127.96,
    "revenue_estimate_high_b": 128.2,
    "revenue_estimate_range_b": "127.96-128.2",
    "sources": ["Nasdaq calendar 2026-10-28 (EPS forecast $2.94, 14 estimates)",
                "MarketBeat (EPS $3.02, revenue $127.96B)",
                "StockInvest (EPS $2.97, revenue $127.962B)",
                "Press coverage (revenue ~$128.2B)"],
    "checked": "2026-10-28/29",
    "basis_note": "Consensus EPS is normally adjusted/non-GAAP; GOOGL GAAP EPS was $2.12. "
                  "Do not present the GAAP-vs-consensus gap as a clean miss without that caveat.",
}


def _quarter_matches(row: dict, quarter: str) -> bool:
    if not quarter:
        return True
    q = quarter.strip().upper().replace(" ", "")
    # Accept "2026Q3", "Q32026", "2026-09-30", "2026-09"
    fiscal = row.get("fiscalDateEnding", "")
    if q in ("2026Q3", "Q32026", "2026-09-30", "2026-09"):
        return fiscal == "2026-09-30"
    return q in fiscal or fiscal.startswith(q)


def parse_alpha_vantage_earnings(data: dict, ticker: str, quarter: str = "") -> dict:
    """Pure parser, unit-testable without a network call."""
    if not isinstance(data, dict) or "quarterlyEarnings" not in data:
        return {"ticker": ticker.upper(), "status": "unavailable",
                "source": "Alpha Vantage",
                "reason": f"Unexpected Alpha Vantage response: {str(data)[:200]}"}
    rows = [r for r in data["quarterlyEarnings"] if _quarter_matches(r, quarter)]
    if not rows:
        return {"ticker": ticker.upper(), "status": "unavailable",
                "source": "Alpha Vantage",
                "reason": f"No quarterly earnings row matched quarter={quarter!r}"}
    # Rows are newest-first; take the first match.
    r = rows[0]
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    return {
        "ticker": ticker.upper(),
        "quarter": quarter or r.get("fiscalDateEnding", ""),
        "fiscal_date_ending": r.get("fiscalDateEnding"),
        "reported_date": r.get("reportedDate"),
        "eps_estimate": _f(r.get("estimatedEPS")),
        "eps_reported": _f(r.get("reportedEPS")),
        "eps_surprise": _f(r.get("surprise")),
        "eps_surprise_pct": _f(r.get("surprisePercentage")),
        "status": "available",
        "source": "Alpha Vantage EARNINGS (free tier, ~25 calls/day)",
        "revenue_estimate": None,
        "revenue_note": "Alpha Vantage EARNINGS gives EPS only, no revenue consensus.",
        "basis_note": "Alpha Vantage does not state GAAP vs adjusted basis. "
                      "Label as 'Alpha Vantage EPS estimate (basis unstated)'.",
    }


def fetch_alpha_vantage_earnings(ticker: str, quarter: str = "", api_key: str = "") -> dict:
    key = api_key or os.environ.get("ALPHA_VANTAGE_API_KEY", "")
    if not key:
        return {"ticker": ticker.upper(), "status": "unavailable",
                "source": "Alpha Vantage",
                "reason": "No ALPHA_VANTAGE_API_KEY set. Get a free key at alphavantage.co and set it in .env."}
    url = (f"https://www.alphavantage.co/query?function=EARNINGS"
           f"&symbol={ticker.strip().upper()}&apikey={key}")
    req = urllib.request.Request(url, headers={"User-Agent": "agent-mesh-earnings/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as e:
        return {"ticker": ticker.upper(), "status": "unavailable",
                "source": "Alpha Vantage", "reason": f"Alpha Vantage request failed: {e}"}
    if "Note" in data or "Information" in data:
        return {"ticker": ticker.upper(), "status": "unavailable",
                "source": "Alpha Vantage",
                "reason": f"Alpha Vantage rate limit / key issue: {data.get('Note') or data.get('Information')}"}
    return parse_alpha_vantage_earnings(data, ticker, quarter)


def _money(v):
    if v is None:
        return None
    try:
        return float(str(v).replace("$", "").replace(",", "").strip())
    except ValueError:
        return None


def parse_nasdaq_calendar(data: dict, ticker: str) -> dict:
    """Pure parser for api.nasdaq.com calendar payload. Verified row (2026-10-28):
    GOOGL eps $2.12, surprise -27.89, epsForecast $2.94, noOfEsts 14,
    fiscalQuarterEnding Sep/2026, time time-not-supplied."""
    try:
        rows = data["data"]["rows"]
        as_of = data["data"].get("asOf")
    except (KeyError, TypeError):
        return {"ticker": ticker.upper(), "status": "unavailable",
                "source": "Nasdaq calendar", "reason": "Unexpected Nasdaq calendar response shape."}
    t = ticker.strip().upper()
    for row in rows:
        if str(row.get("symbol", "")).upper() == t:
            # AMZN Oct 29 2026 case: row exists with a forecast but no
            # reported EPS yet (reported after hours). That is NOT
            # "available" for beat/miss — it is forecast-only.
            if row.get("eps") in (None, ""):
                return {
                    "ticker": t,
                    "fiscal_quarter_ending": row.get("fiscalQuarterEnding"),
                    "eps_estimate": _money(row.get("epsForecast")),
                    "eps_reported": None,
                    "eps_surprise_pct": None,
                    "num_estimates": int(row["noOfEsts"]) if str(row.get("noOfEsts", "")).isdigit() else None,
                    "report_time": row.get("time"),
                    "as_of": as_of,
                    "status": "forecast_only",
                    "source": "Nasdaq earnings calendar (keyless, undocumented public endpoint)",
                    "revenue_estimate": None,
                    "revenue_note": "Nasdaq calendar gives EPS consensus only, no revenue consensus.",
                    "basis_note": "Reported EPS not yet in the Nasdaq row — beat/miss cannot be computed yet.",
                }
            return {
                "ticker": t,
                "fiscal_quarter_ending": row.get("fiscalQuarterEnding"),
                "eps_estimate": _money(row.get("epsForecast")),
                "eps_reported": _money(row.get("eps")),
                "eps_surprise_pct": _money(row.get("surprise")),
                "num_estimates": int(row["noOfEsts"]) if str(row.get("noOfEsts", "")).isdigit() else None,
                "report_time": row.get("time"),
                "as_of": as_of,
                "status": "available",
                "source": "Nasdaq earnings calendar (keyless, undocumented public endpoint)",
                "revenue_estimate": None,
                "revenue_note": "Nasdaq calendar gives EPS consensus only, no revenue consensus.",
                "basis_note": "Nasdaq does not state GAAP vs adjusted basis for the forecast. "
                              "GOOGL reported $2.12 is GAAP; do not present the gap as a clean miss without that caveat.",
            }
    return {"ticker": t, "status": "unavailable",
            "source": "Nasdaq calendar", "reason": f"No {t} row in Nasdaq calendar payload."}


def fetch_nasdaq_calendar(ticker: str, report_date: str) -> dict:
    """Keyless fetch. report_date must be YYYY-MM-DD (the earnings date, not quarter end)."""
    if not report_date:
        return {"ticker": ticker.upper(), "status": "unavailable",
                "source": "Nasdaq calendar", "reason": "No report date supplied for Nasdaq calendar lookup."}
    url = f"https://api.nasdaq.com/api/calendar/earnings?date={report_date}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as e:
        return {"ticker": ticker.upper(), "status": "unavailable",
                "source": "Nasdaq calendar", "reason": f"Nasdaq calendar request failed: {e}"}
    return parse_nasdaq_calendar(data, ticker)


def _is_googl_q3(ticker: str, quarter: str) -> bool:
    t = ticker.strip().upper()
    q = (quarter or "").strip().upper().replace(" ", "")
    return t in ("GOOGL", "GOOG") and (not q or q in ("Q32026", "2026Q3", "2026-09-30", "2026-09"))


def get_consensus(ticker: str, quarter: str = "", report_date: str = "") -> dict:
    """Fallback chain: Nasdaq (keyless) -> Alpha Vantage (key) -> GOOGL Q3 range -> unavailable.
    Nasdaq needs a report date: pass report_date, or GOOGL Q3 2026 defaults to 2026-10-28.
    When Nasdaq succeeds AND an Alpha Vantage key is set, the AV result is
    attached as a cross-check (with a 1.2s pause for AV's 1 req/sec free limit).
    This matters: for GOOGL Q3, Nasdaq reported $2.12 (GAAP, -27.89% vs $2.94)
    while AV reported $2.87 (adjusted, -2.38% vs $2.94). Same estimate, different
    basis — the Critic must never mix them."""
    t = ticker.strip().upper()
    date = report_date or ("2026-10-28" if _is_googl_q3(t, quarter) else "")
    if date:
        nasdaq = fetch_nasdaq_calendar(t, date)
        if nasdaq.get("status") == "forecast_only":
            # Forecast exists, reported EPS does not yet — return it
            # as forecast_only, do not fall through to a stale source.
            return nasdaq
        if nasdaq.get("status") == "available":
            if _is_googl_q3(t, quarter):
                nasdaq["cross_check_range"] = GOOGL_Q3_2026_RANGE
            if os.environ.get("ALPHA_VANTAGE_API_KEY"):
                import time
                time.sleep(1.2)  # Alpha Vantage free tier: 1 request/second
                av = fetch_alpha_vantage_earnings(t, quarter)
                if av.get("status") == "available":
                    nasdaq["alpha_vantage_cross_check"] = av
                    nasdaq["basis_note"] = ("Nasdaq reported EPS is GAAP ($2.12 for GOOGL Q3); "
                                            "Alpha Vantage reported EPS is adjusted ($2.87). "
                                            "Compare consensus only to the matching basis.")
            return nasdaq
    live = fetch_alpha_vantage_earnings(t, quarter)
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
