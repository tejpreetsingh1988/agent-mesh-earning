"""Fiscal.ai-style visuals (Batch 26) — deterministic long-history
charts and unit economics. Everything here is computed, never
written by an LLM.

1. Indexed vs-chart: total return (Nasdaq daily closes +
   dividends reinvested at the ex-date close — an approximation,
   labelled as such) vs any quarterly XBRL series, both rebased
   to 0% at their first common date, legend carrying total change
   + CAGR.
2. Long quarterly bars: up to 40 quarters of one XBRL series +
   a deterministic read line (peak, current vs peak, longest
   rise/decline streaks, biggest QoQ jump — values + dates only,
   never a cause).
3. Head-to-head unit economics: revenue per employee (XBRL
   revenue / DEI headcount). The headcount tag is sparsely
   populated — probed Nov 4, 2026, MSFT, JPM, V, MA and
   Berkshire all carry NO EntityNumberOfEmployees in
   companyfacts — so the row hides for them; nothing is
   estimated. It lights up for any filer that does tag headcount.

The XBRL series reuses async_get_quarterly_facts with limit=40
— the same recency-aware tag pick, YTD differencing, Q4
derivation and derived metrics (EBITDA, FCF) as the briefing
path — so a chart can never disagree with the briefing's
numbers. No forked derivation logic.
"""
import asyncio
import math
import re
from datetime import date, datetime, timedelta

from .async_tools import (_fetch_companyfacts, async_get_company_facts,
                          async_get_quarterly_facts)
from .worker_http import fetch_json as _afetch_json

TICKER_RE = re.compile(r"^[A-Z]{1,5}$")

QUARTERLY_METRICS = {
    "total_revenue", "operating_income", "net_income", "ebitda",
    "operating_cash_flow", "free_cash_flow", "buybacks", "shares_outstanding",
    "gaap_eps",
}
METRIC_LABELS = {
    "total_revenue": "Revenue", "operating_income": "Operating income",
    "net_income": "Net income", "ebitda": "EBITDA",
    "operating_cash_flow": "Operating cash flow",
    "free_cash_flow": "Free cash flow", "buybacks": "Buybacks",
    "shares_outstanding": "Shares outstanding", "headcount": "Headcount",
    "gaap_eps": "GAAP EPS",
}

NASDAQ_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}
HISTORY_LIMIT = 40
SHORT_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def series_label(period_end: str) -> str:
    """ISO date -> 'Sep 2026' (the same short label the frontend
    uses for quarter buttons)."""
    try:
        d = date.fromisoformat(period_end)
    except (TypeError, ValueError):
        return period_end or ""
    return f"{SHORT_MONTHS[d.month - 1]} {d.year}"


def _money(text) -> float | None:
    """Nasdaq '$555.80' / '50,807,830' strings -> float, None when
    unparseable."""
    if text is None:
        return None
    try:
        return float(str(text).replace("$", "").replace(",", "").strip())
    except ValueError:
        return None


def _parse_date(text):
    try:
        return date.fromisoformat(str(text)[:10])
    except (TypeError, ValueError):
        pass
    # Real Nasdaq rows carry MM/DD/YYYY dates (Batch 28's live
    # probe); without this branch every real row was dropped and
    # the vs-chart silently hid. ISO stays first so existing
    # callers are unaffected.
    try:
        return datetime.strptime(str(text).strip(), "%m/%d/%Y").date()
    except (TypeError, ValueError):
        return None


def total_change_pct(first: float, last: float) -> float | None:
    if not first or first <= 0 or last is None or last <= 0:
        return None
    return (last / first - 1) * 100


def cagr_pct(first: float, last: float, first_d: date, last_d: date) -> float | None:
    """(end/start)^(1/years) - 1, in percent. None when the inputs
    cannot support it (non-positive values, no time span)."""
    if not first or first <= 0 or last is None or last <= 0:
        return None
    if not first_d or not last_d:
        return None
    days = (last_d - first_d).days
    if days <= 0:
        return None
    return ((last / first) ** (365.25 / days) - 1) * 100


def rebase(points: list[dict]) -> list[dict]:
    """Copy points (ascending, each with period_end + value) with
    a value_pct field: % change from the first point (0.0 at the
    start). Empty or a non-positive first value -> []."""
    if len(points) < 2:
        return []
    first = points[0]["value"]
    if not first or first <= 0:
        return []
    out = []
    for p in points:
        if p["value"] is None or p["value"] <= 0:
            continue
        out.append({**p, "value_pct": (p["value"] / first - 1) * 100})
    return out if len(out) >= 2 else []


def build_total_return(closes: list[dict], dividends: list[dict]) -> list[dict]:
    """Daily total-return index from Nasdaq closes + dividends.
    closes: [{date, close}] newest first or oldest first (sorted
    here); dividends: [{exOrEffDate, amount, type}]. Each dividend
    reinvests at the close on its ex-date: index *= (P + D) / P_prev.
    Dividends outside the close range (e.g. a declared future
    ex-date) are ignored. First day's index is 1.0."""
    rows = []
    for c in closes:
        d = _parse_date(c.get("date"))
        price = _money(c.get("close"))
        if d and price:
            rows.append((d, price))
    rows.sort()
    if not rows:
        return []
    div_by_date: dict[date, float] = {}
    for dv in dividends or []:
        if str(dv.get("type", "Cash")) != "Cash":
            continue
        d = _parse_date(dv.get("exOrEffDate"))
        amount = _money(dv.get("amount"))
        if d and amount:
            div_by_date[d] = div_by_date.get(d, 0.0) + amount
    out = []
    index = 1.0
    prev_price = None
    for d, price in rows:
        if prev_price is not None:
            div = div_by_date.get(d, 0.0)
            index *= (price + div) / prev_price
        prev_price = price
        out.append({"date": d.isoformat(), "index": index})
    return out


def sample_total_return(tr_index: list[dict], quarter_ends: list[str]) -> list[dict]:
    """Sample the daily total-return index at each quarter end:
    the last index value on or before that date. Quarters with no
    close on or before them are dropped."""
    if not tr_index:
        return []
    pts = []
    for end in quarter_ends:
        ed = _parse_date(end)
        if not ed:
            continue
        value = None
        for row in tr_index:
            if _parse_date(row["date"]) <= ed:
                value = row["index"]
            else:
                break
        if value is not None:
            pts.append({"period_end": end, "value": value})
    return pts


def read_line(points: list[dict]) -> dict | None:
    """Deterministic read line for a quarterly/annual series
    (ascending, each with period_end + value): peak value + date,
    current vs peak %, longest rise/decline streaks in quarters,
    biggest QoQ jump (values + dates, never a cause). None when
    fewer than 2 points."""
    if len(points) < 2:
        return None
    vals = [(p["period_end"], p["value"]) for p in points
            if p.get("value") is not None]
    if len(vals) < 2:
        return None
    peak_end, peak_val = max(vals, key=lambda kv: kv[1])
    cur_end, cur_val = vals[-1]
    vs_peak = ((cur_val / peak_val - 1) * 100) if peak_val else None
    best_rise = best_decline = 1
    run_rise = run_decline = 1
    biggest = None
    for i in range(1, len(vals)):
        prev_end, prev = vals[i - 1]
        end, val = vals[i]
        if val > prev:
            run_rise += 1
            run_decline = 1
        elif val < prev:
            run_decline += 1
            run_rise = 1
        else:
            run_rise = run_decline = 1
        best_rise = max(best_rise, run_rise)
        best_decline = max(best_decline, run_decline)
        if prev:
            pct = (val / prev - 1) * 100
            if biggest is None or abs(pct) > abs(biggest["pct"]):
                biggest = {"from_end": prev_end, "to_end": end,
                           "from_value": prev, "to_value": val, "pct": pct}
    return {"peak_value": peak_val, "peak_end": peak_end,
            "current_value": cur_val, "current_end": cur_end,
            "current_vs_peak_pct": vs_peak,
            "longest_rise_quarters": best_rise,
            "longest_decline_quarters": best_decline,
            "biggest_jump": biggest}


def headcount_from_companyfacts(cf: dict) -> dict | None:
    """Latest DEI headcount row from a companyfacts payload, or
    None when the filer does not tag it (the common case — see
    the module docstring)."""
    if not isinstance(cf, dict):
        return None
    tag = (cf.get("facts") or {}).get("dei", {}).get("EntityNumberOfEmployees") or {}
    rows = []
    for unit_rows in (tag.get("units") or {}).values():
        for r in unit_rows:
            end = r.get("end")
            val = r.get("val")
            if end and val is not None:
                rows.append({"period_end": end, "value": val,
                             "fy": r.get("fy"), "form": r.get("form")})
    if not rows:
        return None
    rows.sort(key=lambda r: r["period_end"])
    return rows[-1]


async def _nasdaq_series(ticker: str, from_date: date, to_date: date,
                          fetch_json=_afetch_json):
    """Nasdaq daily closes + dividends in parallel. Each source
    failing yields None for that source (the vs-chart hides;
    the long bars still render)."""
    base = f"https://api.nasdaq.com/api/quote/{ticker}"

    async def _closes():
        try:
            body = await fetch_json(
                f"{base}/historical?assetclass=stocks"
                f"&fromdate={from_date.isoformat()}&todate={to_date.isoformat()}&limit=9999",
                headers=NASDAQ_HEADERS)
            return (((body or {}).get("data") or {}).get("tradesTable") or {}).get("rows") or []
        except Exception:
            return None

    async def _dividends():
        try:
            body = await fetch_json(f"{base}/dividends?assetclass=stocks",
                                    headers=NASDAQ_HEADERS)
            return (((body or {}).get("data") or {}).get("dividends") or {}).get("rows") or []
        except Exception:
            return None

    return await asyncio.gather(_closes(), _dividends())


async def history_for_ticker(ticker: str, metric: str, fetch_json=_afetch_json) -> dict:
    """One history payload for the /history route. Quarterly
    metrics come from async_get_quarterly_facts(limit=40);
    'headcount' comes from companyfacts (annual 10-K rows).
    Data failures degrade to empty/null parts, never an
    exception — only a bad ticker or metric raises ValueError
    (the route turns it into a 400)."""
    t = (ticker or "").strip().upper()
    if not TICKER_RE.match(t):
        raise ValueError(f"Invalid ticker for history fetch: {ticker!r}")
    m = (metric or "").strip().lower()
    if m != "headcount" and m not in QUARTERLY_METRICS:
        raise ValueError(f"Unknown history metric: {metric!r}")
    facts = await async_get_company_facts(t)
    if "error" in facts:
        return {"ticker": t, "metric": m, "frequency": "annual" if m == "headcount" else "quarterly",
                "series": [], "unit": "", "total_return": None,
                "metric_total_change_pct": None, "metric_cagr_pct": None,
                "read_line": None, "error": facts["error"]}
    cik = facts["cik"]

    if m == "headcount":
        try:
            cf = await _fetch_companyfacts(cik)
            latest = headcount_from_companyfacts(cf)
        except Exception:
            latest = None
        series = []
        if latest:
            series = [{"period_end": latest["period_end"], "value": latest["value"],
                       "label": f"FY{latest['fy']}" if latest.get("fy") else series_label(latest["period_end"])}]
        return {"ticker": t, "metric": m, "frequency": "annual", "series": series,
                "unit": "employees", "total_return": None,
                "metric_total_change_pct": None, "metric_cagr_pct": None,
                "read_line": read_line(series), "error": None}

    qfacts = await async_get_quarterly_facts(
        cik, limit=HISTORY_LIMIT, companyfacts_fetch=_fetch_companyfacts)
    entry = (qfacts or {}).get(m) or {}
    rows = [r for r in (entry.get("rows") or [])
            if r.get("value") is not None and _parse_date(r.get("period_end"))]
    rows.sort(key=lambda r: r["period_end"])
    rows = rows[-HISTORY_LIMIT:]
    series = [{"period_end": r["period_end"], "value": r["value"],
               "label": series_label(r["period_end"])} for r in rows]
    unit = (entry.get("rows") or [{}])[0].get("unit", "") if entry.get("rows") else ""
    out = {"ticker": t, "metric": m, "frequency": "quarterly", "series": series,
           "unit": unit, "total_return": None,
           "metric_total_change_pct": None, "metric_cagr_pct": None,
           "read_line": read_line(series), "error": None}
    if len(series) < 2:
        return out
    first_d = _parse_date(series[0]["period_end"])
    last_d = _parse_date(series[-1]["period_end"])
    out["metric_total_change_pct"] = total_change_pct(series[0]["value"], series[-1]["value"])
    out["metric_cagr_pct"] = cagr_pct(series[0]["value"], series[-1]["value"], first_d, last_d)
    # Total return: Nasdaq closes from a year before the first
    # quarter end (the first TR step needs a prior close) to
    # today, sampled at the series' quarter ends. The long-bars
    # chart keeps the FULL series; the vs-chart gets its own
    # rebased metric points over the quarters both series share.
    full_rebased = {p["period_end"]: p["value_pct"] for p in rebase(series)}
    out["series"] = [{**p, "value_pct": full_rebased.get(p["period_end"])} for p in series]
    closes, dividends = await _nasdaq_series(
        t, first_d - timedelta(days=400), date.today(), fetch_json=fetch_json)
    if closes is None:
        return out
    tr = build_total_return(closes, dividends or [])
    sampled = sample_total_return(tr, [p["period_end"] for p in series])
    if len(sampled) < 2:
        return out
    # First common date: the later of the two series' starts.
    common = max(sampled[0]["period_end"], series[0]["period_end"])
    tr_trim = [p for p in sampled if p["period_end"] >= common]
    metric_trim = [p for p in series if p["period_end"] >= common]
    tr_rebased = rebase(tr_trim)
    metric_rebased = rebase(metric_trim)
    if len(tr_rebased) < 2 or len(metric_rebased) < 2:
        return out
    # Rebased points share the quarter axis; keep only quarters
    # present in both (a missing TR sample drops that quarter).
    tr_by_end = {p["period_end"]: p["value_pct"] for p in tr_rebased}
    metric_by_end = {p["period_end"]: p["value_pct"] for p in metric_rebased}
    common_ends = sorted(set(tr_by_end) & set(metric_by_end))
    if len(common_ends) < 2:
        return out
    out["total_return"] = {
        "points": [{"period_end": e, "value_pct": tr_by_end[e]} for e in common_ends],
        "metric_points": [{"period_end": e, "value_pct": metric_by_end[e]} for e in common_ends],
        "total_change_pct": total_change_pct(tr_rebased[0]["value"], tr_rebased[-1]["value"]),
        "cagr_pct": cagr_pct(tr_rebased[0]["value"], tr_rebased[-1]["value"],
                             _parse_date(tr_rebased[0]["period_end"]),
                             _parse_date(tr_rebased[-1]["period_end"])),
        "note": "Total return reinvests each dividend at the close on its ex-date — an approximation.",
    }
    return out
