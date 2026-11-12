"""Earnings calendar strip (Feature 11) — who reports this week.

Nasdaq keyless earnings calendar, Worker-side (the browser must
not be assumed to have CORS for it):
`GET https://api.nasdaq.com/api/calendar/earnings?date=YYYY-MM-DD`
(one call per day, 7 calls, same UA/Accept headers as the
existing Nasdaq calls). Shape pinned by the V1 live probe
(2026-10-28: 247 rows; empty Sunday 2026-11-08: `rows: null`):
`{data: {asOf, headers, rows}, message, status}`; row fields
`symbol, name, eps, epsForecast, noOfEsts, surprise, time,
marketCap, fiscalQuarterEnding`. Only symbol + name are used
in v1 — no report time is shown (the shape carries `time`,
but values like "time-not-supplied" are not a time), and no
estimate is shown even though the shape carries epsForecast.

The route returns every row for each day; the frontend filters
to directory tickers (it already holds web/companies/
companies.json for search). A day whose call fails returns
`error: true` for that day — the strip shows "Calendar
unavailable for this day", never a partial day as complete.
"""
import asyncio
from datetime import date, timedelta

from .market import NASDAQ_HEADERS
from .worker_http import fetch_json as _afetch_json

CALENDAR_URL = "https://api.nasdaq.com/api/calendar/earnings?date={day}"
DAYS = 7


def parse_calendar_day(body):
    """[{ticker, name}] for one day's Nasdaq calendar response.
    `rows: null` (an empty day) is an empty list, not an error;
    a row without a symbol is dropped."""
    rows = ((body or {}).get("data") or {}).get("rows") or []
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        symbol = (r.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        out.append({"ticker": symbol, "name": (r.get("name") or "").strip()})
    return out


async def _day(day_iso, fetch_json=_afetch_json):
    try:
        body = await fetch_json(CALENDAR_URL.format(day=day_iso),
                                headers=NASDAQ_HEADERS)
        return {"date": day_iso, "rows": parse_calendar_day(body)}
    except Exception:
        return {"date": day_iso, "error": True, "rows": []}


async def calendar_for_week(today=None, fetch_json=_afetch_json):
    """{days: [{date, rows} | {date, error, rows: []}]} for today
    + 6 days. The 7 day-fetches run in parallel; one day's
    failure never takes down the others."""
    start = today or date.today()
    days = [(start + timedelta(days=i)).isoformat() for i in range(DAYS)]
    return {"days": await asyncio.gather(*[_day(d, fetch_json) for d in days])}
