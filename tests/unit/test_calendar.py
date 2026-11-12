"""Earnings calendar strip (Feature 11): the parser with the
V1-verified Nasdaq shape — 247-row days, `rows: null` empty
days, rows without a symbol. Network is stubbed; the live
check is the strip rendering on the deployed site."""
import asyncio
from datetime import date

from mesh import calendar


def _body(rows):
    return {"data": {"asOf": "2026-10-28", "headers": {},
                     "rows": rows},
            "message": None, "status": {"rCode": 200}}


def test_parse_calendar_day_verified_shape():
    body = _body([
        {"symbol": "GOOGL", "name": "Alphabet Inc.", "eps": 2.12,
         "epsForecast": 2.94, "noOfEsts": 10, "surprise": -27.89,
         "time": "time-not-supplied", "marketCap": 123456789,
         "fiscalQuarterEnding": "Sep 2026"},
        {"symbol": "MSFT", "name": "Microsoft Corporation", "eps": 3.5,
         "epsForecast": 3.4, "noOfEsts": 12, "surprise": 2.94,
         "time": "time-bmo", "marketCap": 987654321,
         "fiscalQuarterEnding": "Sep 2026"},
    ])
    assert calendar.parse_calendar_day(body) == [
        {"ticker": "GOOGL", "name": "Alphabet Inc."},
        {"ticker": "MSFT", "name": "Microsoft Corporation"}]


def test_parse_calendar_day_rows_null_is_empty():
    assert calendar.parse_calendar_day(_body(None)) == []


def test_parse_calendar_day_drops_symbol_less_rows():
    body = _body([{"name": "No Ticker Corp."}, {"symbol": "  ", "name": "Blank"},
                  {"symbol": "nvda", "name": "NVIDIA Corporation"}])
    assert calendar.parse_calendar_day(body) == [
        {"ticker": "NVDA", "name": "NVIDIA Corporation"}]


def test_calendar_for_week_seven_days():
    async def fetch_json(url, headers=None):
        day = url.rsplit("=", 1)[1]
        return _body([{"symbol": "MSFT", "name": "Microsoft Corporation"}]) \
            if day != "2026-11-08" else _body(None)

    out = asyncio.run(calendar.calendar_for_week(
        today=date(2026, 11, 5), fetch_json=fetch_json))
    assert [d["date"] for d in out["days"]] == [
        "2026-11-05", "2026-11-06", "2026-11-07", "2026-11-08",
        "2026-11-09", "2026-11-10", "2026-11-11"]
    assert out["days"][0]["rows"] == [{"ticker": "MSFT", "name": "Microsoft Corporation"}]
    assert out["days"][3]["rows"] == []  # the empty Sunday


def test_calendar_for_week_failed_day_is_error():
    async def fetch_json(url, headers=None):
        if "2026-11-06" in url:
            raise RuntimeError("Nasdaq down")
        return _body([])

    out = asyncio.run(calendar.calendar_for_week(
        today=date(2026, 11, 5), fetch_json=fetch_json))
    assert out["days"][1] == {"date": "2026-11-06", "error": True, "rows": []}
    assert out["days"][0]["rows"] == []  # the other days still land
    assert len(out["days"]) == 7
