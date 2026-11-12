"""Earnings calendar (Feature 11) — who reports, in a month grid.

Nasdaq keyless earnings calendar, Worker-side (the browser must
not be assumed to have CORS for it):
`GET https://api.nasdaq.com/api/calendar/earnings?date=YYYY-MM-DD`
(one call per day, same UA/Accept headers as the existing Nasdaq
calls). Shape pinned by the V1 live probe (2026-10-28: 247 rows;
empty Sunday 2026-11-08: `rows: null`):
`{data: {asOf, headers, rows}, message, status}`; row fields
`symbol, name, eps, epsForecast, noOfEsts, surprise, time,
marketCap, fiscalQuarterEnding`.

Batch 66: the strip (7 dated rows of chips) became a month grid,
so the rows now carry the report timing too. Nasdaq's `time`
field is real and well-populated (Nov 12, 2026: 124
after-hours, 64 pre-market, 162 not-supplied out of 350):
`time-pre-market` -> "before" (before market open),
`time-after-hours` -> "after" (after market close), anything
else (incl. `time-not-supplied` or missing) -> None, shown with
no timing pill — never guessed.

The route returns every row for each day; the frontend filters
to directory tickers (it already holds web/companies/
companies.json for search). A day whose call fails returns
`error: true` for that day — the grid marks it unavailable,
never a partial day as complete. A month is ~30 parallel
Nasdaq calls, so they run under a semaphore (8 in flight) to
avoid tripping Nasdaq's keyless rate limit.
"""
import asyncio
import calendar as _calendar
from datetime import date, timedelta

from .market import NASDAQ_HEADERS
from .worker_http import fetch_json as _afetch_json

CALENDAR_URL = "https://api.nasdaq.com/api/calendar/earnings?date={day}"
DAYS = 7
_MONTH_CONCURRENCY = 8

# Nasdaq `time` values -> the grid's timing pill. Only these two
# are ever shown; "time-not-supplied" (and anything unknown)
# maps to None, i.e. no pill.
_TIME_MAP = {"time-pre-market": "before", "time-after-hours": "after"}


def parse_calendar_day(body):
    """[{ticker, name, time}] for one day's Nasdaq calendar
    response. `rows: null` (an empty day) is an empty list, not
    an error; a row without a symbol is dropped. `time` is
    "before" | "after" | None (Batch 66)."""
    rows = ((body or {}).get("data") or {}).get("rows") or []
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        symbol = (r.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        out.append({"ticker": symbol, "name": (r.get("name") or "").strip(),
                    "time": _TIME_MAP.get((r.get("time") or "").strip())})
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


async def calendar_for_month(year, month, fetch_json=_afetch_json):
    """{month: "YYYY-MM", days: [...]} for every day of the
    month, in date order (Batch 66). The day-fetches run under
    a semaphore so a 30-day month does not fire 30 parallel
    Nasdaq calls at once; one day's failure never takes down
    the others."""
    _, last = _calendar.monthrange(year, month)
    days = [date(year, month, d).isoformat() for d in range(1, last + 1)]
    sem = asyncio.Semaphore(_MONTH_CONCURRENCY)

    async def _guarded(day_iso):
        async with sem:
            return await _day(day_iso, fetch_json)

    return {"month": f"{year:04d}-{month:02d}",
            "days": await asyncio.gather(*[_guarded(d) for d in days])}
