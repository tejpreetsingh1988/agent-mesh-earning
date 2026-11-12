"""GET /news route (Feature 24): thin wrapper over
mesh/news_rss.py — returns the payload, 400s on a bad
ticker. The data leg itself is covered by test_news_rss.py;
this only pins the route wiring, with the fetcher stubbed
out."""
import asyncio
import importlib.util
import pathlib


def _load_worker_main():
    spec = importlib.util.spec_from_file_location(
        "orch_worker_main_news_test",
        pathlib.Path(__file__).resolve().parents[2] / "apps" / "orchestrator" / "worker_main.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_news_route_returns_payload(monkeypatch):
    mod = _load_worker_main()
    payload = {"ticker": "MSFT", "report_date": "2026-10-28",
               "news": [{"title": "Microsoft beats on cloud growth",
                         "publisher": "Reuters",
                         "url": "https://news.google.com/rss/articles/CBMiTest1",
                         "published": "2026-10-28"}]}

    async def fake(ticker):
        assert ticker == "MSFT"
        return payload

    monkeypatch.setattr(mod, "news_for_ticker", fake)
    assert asyncio.run(mod.news(ticker="MSFT")) == payload


def test_news_route_400_on_bad_ticker():
    mod = _load_worker_main()
    resp = asyncio.run(mod.news(ticker="!!!"))
    assert resp.status_code == 400
    assert "error" in resp.body.decode()
