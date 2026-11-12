"""GET /dividends route (Feature 14): thin wrapper over
mesh/dividends.py — returns the payload, 400s on a bad ticker.
The data leg itself is covered by test_dividends.py; this only
pins the route wiring, with the fetcher stubbed out."""
import asyncio
import importlib.util
import pathlib

import pytest


def _load_worker_main():
    spec = importlib.util.spec_from_file_location(
        "orch_worker_main_dividends_test",
        pathlib.Path(__file__).resolve().parents[2] / "apps" / "orchestrator" / "worker_main.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_dividends_route_returns_payload(monkeypatch):
    mod = _load_worker_main()
    payload = {"ticker": "MSFT", "rows": [{"ex_date": "2026-08-20", "amount": 0.91}],
               "next_ex_date": None, "trailing_yield": 0.7, "last_close": 493.95}

    async def fake(ticker):
        assert ticker == "MSFT"
        return payload

    monkeypatch.setattr(mod, "dividends_for_ticker", fake)
    assert asyncio.run(mod.dividends(ticker="MSFT")) == payload


def test_dividends_route_400_on_bad_ticker():
    mod = _load_worker_main()
    resp = asyncio.run(mod.dividends(ticker="!!!"))
    assert resp.status_code == 400
    assert "error" in resp.body.decode()
