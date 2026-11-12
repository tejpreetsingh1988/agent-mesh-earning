"""GET /calendar route (Feature 11): thin wrapper over
mesh/calendar.py — returns the week's days as-is. The data leg
itself is covered by test_calendar.py; this only pins the
route wiring, with the fetcher stubbed out."""
import asyncio
import importlib.util
import pathlib


def _load_worker_main():
    spec = importlib.util.spec_from_file_location(
        "orch_worker_main_calendar_test",
        pathlib.Path(__file__).resolve().parents[2] / "apps" / "orchestrator" / "worker_main.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_calendar_route_returns_week(monkeypatch):
    mod = _load_worker_main()
    payload = {"days": [{"date": "2026-11-05",
                         "rows": [{"ticker": "MSFT", "name": "Microsoft Corporation"}]},
                        {"date": "2026-11-06", "error": True, "rows": []}]}

    async def fake():
        return payload

    monkeypatch.setattr(mod, "calendar_for_week", fake)
    assert asyncio.run(mod.calendar()) == payload
