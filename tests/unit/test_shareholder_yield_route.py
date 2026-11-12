"""GET /shareholder-yield route (Feature 15): thin wrapper over
mesh/shareholder_yield.py — returns the payload, null when any
input is missing, 400s on a bad ticker. The data leg itself is
covered by test_shareholder_yield.py; this only pins the route
wiring, with the fetcher stubbed out."""
import asyncio
import importlib.util
import pathlib


def _load_worker_main():
    spec = importlib.util.spec_from_file_location(
        "orch_worker_main_yield_test",
        pathlib.Path(__file__).resolve().parents[2] / "apps" / "orchestrator" / "worker_main.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_shareholder_yield_route_returns_payload(monkeypatch):
    mod = _load_worker_main()
    payload = {"ticker": "MSFT", "buybacks_trailing_usd": 21_000_000_000,
               "dividends_trailing_usd": 27_030_000_000,
               "market_cap_usd": 3_668_168_798_960, "shareholder_yield": 1.3,
               "shares_outstanding": 7_426_194_552, "last_close": 493.95,
               "approximation_note": "Dividends total uses the latest share count for all four quarters — an approximation."}

    async def fake(ticker):
        assert ticker == "MSFT"
        return payload

    monkeypatch.setattr(mod, "shareholder_yield_for_ticker", fake)
    assert asyncio.run(mod.shareholder_yield(ticker="MSFT")) == payload


def test_shareholder_yield_route_null_on_missing_input(monkeypatch):
    mod = _load_worker_main()

    async def fake(ticker):
        return None  # e.g. BROS: no buyback series

    monkeypatch.setattr(mod, "shareholder_yield_for_ticker", fake)
    assert asyncio.run(mod.shareholder_yield(ticker="BROS")) is None


def test_shareholder_yield_route_400_on_bad_ticker():
    mod = _load_worker_main()
    resp = asyncio.run(mod.shareholder_yield(ticker="!!!"))
    assert resp.status_code == 400
    assert "error" in resp.body.decode()
