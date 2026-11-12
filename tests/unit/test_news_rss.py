"""News around earnings (Feature 24): the RSS parser with the
V3-verified Google News shape, the ±7-day window filter (cap
10, newest first), and the route payload with stubbed fetches.
Network is stubbed throughout; the live check is the card on
a deployed briefing (Worker-side fetchability is the one
unproven leg)."""
import asyncio

import pytest

from mesh import news_rss as nr

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<title>MSFT stock - Google News</title>
<item><title>Microsoft beats on cloud growth</title>
<link>https://news.google.com/rss/articles/CBMiTest1</link>
<guid>1</guid><pubDate>Wed, 28 Oct 2026 14:30:00 GMT</pubDate>
<source url="https://www.reuters.com">Reuters</source></item>
<item><title>Microsoft stock falls after guidance</title>
<link>https://news.google.com/rss/articles/CBMiTest2</link>
<guid>2</guid><pubDate>Thu, 29 Oct 2026 09:00:00 GMT</pubDate>
<source url="https://www.bloomberg.com">Bloomberg</source></item>
<item><title>An old Microsoft story</title>
<link>https://news.google.com/rss/articles/CBMiTest3</link>
<guid>3</guid><pubDate>Mon, 12 Oct 2026 09:00:00 GMT</pubDate>
<source url="https://www.wsj.com">The Wall Street Journal</source></item>
<item><title>No link, dropped</title>
<guid>4</guid><pubDate>Wed, 28 Oct 2026 14:30:00 GMT</pubDate>
<source url="https://www.reuters.com">Reuters</source></item>
<item><title>No source, publisher empty</title>
<link>https://news.google.com/rss/articles/CBMiTest5</link>
<guid>5</guid><pubDate>Wed, 28 Oct 2026 14:30:00 GMT</pubDate></item>
</channel></rss>"""


def test_parse_rss_items_verified_shape():
    items = nr.parse_rss_items(RSS)
    assert items[0] == {"title": "Microsoft beats on cloud growth",
                        "publisher": "Reuters",
                        "url": "https://news.google.com/rss/articles/CBMiTest1",
                        "published": "2026-10-28"}
    assert items[1]["publisher"] == "Bloomberg"
    assert items[1]["published"] == "2026-10-29"
    # The link-less item is dropped; the source-less item keeps
    # an empty publisher.
    assert len(items) == 4
    assert items[3] == {"title": "No source, publisher empty",
                        "publisher": "",
                        "url": "https://news.google.com/rss/articles/CBMiTest5",
                        "published": "2026-10-28"}


def test_parse_rss_items_malformed_is_empty():
    assert nr.parse_rss_items("<rss><channel><item>") == []
    assert nr.parse_rss_items("") == []


def test_filter_window_seven_days_cap_newest_first():
    items = [{"title": f"n{i}", "publisher": "P", "url": f"u{i}",
              "published": d} for i, d in enumerate([
                  "2026-10-21",  # exactly -7d: in
                  "2026-10-20",  # -8d: out
                  "2026-11-04",  # exactly +7d: in
                  "2026-11-05",  # +8d: out
                  "2026-10-28", "2026-10-29", "2026-10-27",
                  "2026-10-30", "2026-10-26", "2026-10-31",
                  "2026-11-01", "2026-11-02", "2026-11-03",
                  "2026-10-25", "2026-10-24", "2026-10-23",
                  "2026-10-22", "2026-10-21"])]
    out = nr.filter_window(items, "2026-10-28")
    assert len(out) == 10  # capped, even though 14 fall in-window
    assert out[0]["published"] == "2026-11-04"  # newest first
    assert out[-1]["published"] == "2026-10-26"  # cap keeps the 10 newest
    assert all("2026-10-20" != it["published"] and "2026-11-05" != it["published"]
               for it in out)


def test_filter_window_bad_report_date():
    assert nr.filter_window([{"published": "2026-10-28"}], "not-a-date") == []
    assert nr.filter_window([{"published": ""}], "2026-10-28") == []


def test_news_for_ticker_window_applied(monkeypatch):
    async def fake_report_date(ticker, fetch_json=None):
        assert ticker == "MSFT"
        return "2026-10-28"

    async def fake_text(url, headers=None):
        assert "news.google.com/rss/search" in url
        assert "q=MSFT+stock" in url
        return RSS

    monkeypatch.setattr(nr, "report_date_for_ticker", fake_report_date)
    out = asyncio.run(nr.news_for_ticker("MSFT", fake_text, None))
    assert out["ticker"] == "MSFT"
    assert out["report_date"] == "2026-10-28"
    # The Oct 12 item is outside ±7 days; the rest are in.
    assert [n["title"] for n in out["news"]] == [
        "Microsoft stock falls after guidance",
        "Microsoft beats on cloud growth",
        "No source, publisher empty"]
    assert out["news"][0]["url"].startswith("https://news.google.com/rss/articles/")


def test_news_for_ticker_feed_failure_hides(monkeypatch):
    async def fake_report_date(ticker, fetch_json=None):
        return "2026-10-28"

    async def fake_text(url, headers=None):
        raise RuntimeError("Google blocked the Worker")

    monkeypatch.setattr(nr, "report_date_for_ticker", fake_report_date)
    out = asyncio.run(nr.news_for_ticker("MSFT", fake_text, None))
    assert out == {"ticker": "MSFT", "report_date": "2026-10-28", "news": []}


def test_news_for_ticker_no_report_date(monkeypatch):
    async def fake_report_date(ticker, fetch_json=None):
        return None

    monkeypatch.setattr(nr, "report_date_for_ticker", fake_report_date)
    out = asyncio.run(nr.news_for_ticker("MSFT", None, None))
    assert out == {"ticker": "MSFT", "report_date": None, "news": []}


def test_news_for_ticker_bad_ticker():
    with pytest.raises(ValueError):
        asyncio.run(nr.news_for_ticker("!!!"))
