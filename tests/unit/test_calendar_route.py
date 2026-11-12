"""GET /calendar route (Feature 11, Batch 66): thin wrapper over
mesh/calendar.py — returns the requested month's days as-is.
The data leg itself is covered by test_calendar.py; this only
pins the route wiring (month param, current-month default,
invalid-month fallback), with the fetcher stubbed out."""
import asyncio
import importlib.util
import pathlib
from datetime import date


def _load_worker_main():
    spec = importlib.util.spec_from_file_location(
        "orch_worker_main_calendar_test",
        pathlib.Path(__file__).resolve().parents[2] / "apps" / "orchestrator" / "worker_main.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_calendar_route_returns_month(monkeypatch):
    mod = _load_worker_main()
    payload = {"month": "2026-11",
               "days": [{"date": "2026-11-05",
                         "rows": [{"ticker": "MSFT", "name": "Microsoft Corporation",
                                   "time": "after"}]},
                        {"date": "2026-11-06", "error": True, "rows": []}]}
    seen = {}

    async def fake(year, month):
        seen["args"] = (year, month)
        return payload

    monkeypatch.setattr(mod, "calendar_for_month", fake)
    assert asyncio.run(mod.calendar(month="2026-11")) == payload
    assert seen["args"] == (2026, 11)


def test_calendar_route_defaults_to_current_month(monkeypatch):
    mod = _load_worker_main()
    seen = {}

    async def fake(year, month):
        seen["args"] = (year, month)
        return {"month": f"{year:04d}-{month:02d}", "days": []}

    monkeypatch.setattr(mod, "calendar_for_month", fake)
    today = date.today()
    assert asyncio.run(mod.calendar(month=""))["month"] == (
        f"{today.year:04d}-{today.month:02d}")
    assert seen["args"] == (today.year, today.month)


def test_calendar_route_invalid_month_falls_back(monkeypatch):
    mod = _load_worker_main()
    seen = {}

    async def fake(year, month):
        seen["args"] = (year, month)
        return {"month": f"{year:04d}-{month:02d}", "days": []}

    monkeypatch.setattr(mod, "calendar_for_month", fake)
    today = date.today()
    for bad in ["2026-13", "november", "2026-1", "2026/11"]:
        asyncio.run(mod.calendar(month=bad))
        assert seen["args"] == (today.year, today.month)
