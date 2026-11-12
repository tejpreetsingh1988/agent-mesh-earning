"""GET /past-reactions route (Feature 20): thin wrapper over
mesh/past_reactions.py — returns the payload, 400s on a bad
ticker. The data leg itself is covered by
test_past_reactions.py; this only pins the route wiring, with
the fetcher stubbed out."""
import asyncio
import importlib.util
import pathlib


def _load_worker_main():
    spec = importlib.util.spec_from_file_location(
        "orch_worker_main_reactions_test",
        pathlib.Path(__file__).resolve().parents[2] / "apps" / "orchestrator" / "worker_main.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_past_reactions_route_returns_payload(monkeypatch):
    mod = _load_worker_main()
    payload = {"ticker": "GOOGL",
               "rows": [{"quarter_end": "2026-09-30", "report_date": "2026-10-28",
                         "close_before": 324.89, "close_after": 283.82, "change_pct": -12.6}],
               "omitted": 0}

    async def fake(ticker):
        assert ticker == "GOOGL"
        return payload

    monkeypatch.setattr(mod, "past_reactions_for_ticker", fake)
    assert asyncio.run(mod.past_reactions(ticker="GOOGL")) == payload


def test_past_reactions_route_400_on_bad_ticker():
    mod = _load_worker_main()
    resp = asyncio.run(mod.past_reactions(ticker="!!!"))
    assert resp.status_code == 400
    assert "error" in resp.body.decode()
