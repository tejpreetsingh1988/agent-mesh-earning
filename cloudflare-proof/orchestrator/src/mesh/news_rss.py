"""News around earnings (Feature 24) — headlines + dates only,
no machine-written summary.

Source (V3-verified): Google News RSS, no key —
`https://news.google.com/rss/search?q={T}+stock&hl=en-US&gl=US&ceid=US:en`
(87 items for MSFT in the probe). Fields: title, publisher
(`<source>` text), published (`<pubDate>`), URL. The URL is
Google's redirect link (`news.google.com/rss/articles/...`),
which clicks through to the publisher article; v1 does NOT
resolve it to the publisher's canonical URL and must not
claim to. `mesh/news.py::get_recent_news` is yfinance-based
and cannot run on the Worker path — it is not used here.

The window is fixed (±7 days around the briefing's report
date); rows outside it are dropped, never shown as "related".
The report date comes from `past_reactions.report_date_for_ticker`
— the same earnings-8-K identification the Scout used — because
the Briefing schema does not carry it. If the report date cannot
be identified, or the feed fails, or nothing falls in the window,
the route returns an empty list and the card hides (hide-on-failure;
Worker-side fetchability is the one unproven leg, and the first
live run is its proof).

Headlines are displayed verbatim as published. The frontend
never extracts a number from a headline, and headlines are
never cited in the Sources section as briefing sources.
"""
import asyncio
import email.utils
import xml.etree.ElementTree as ET
from datetime import date, timedelta

from .market import NASDAQ_HEADERS
from .past_reactions import report_date_for_ticker
from .worker_http import fetch_json as _afetch_json
from .worker_http import fetch_text as _afetch_text

RSS_URL = ("https://news.google.com/rss/search?q={ticker}+stock"
           "&hl=en-US&gl=US&ceid=US:en")
WINDOW_DAYS = 7
MAX_ROWS = 10


def parse_rss_items(xml_text):
    """[{title, publisher, url, published}] from a Google News
    RSS document. `published` is an ISO date (YYYY-MM-DD).
    An item without a title or URL is dropped; a missing
    `<source>` means an empty publisher, never an error."""
    out = []
    try:
        root = ET.fromstring(xml_text or "")
    except ET.ParseError:
        return []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        url = (item.findtext("link") or "").strip()
        if not title or not url:
            continue
        source_el = item.find("source")
        publisher = (source_el.text or "").strip() if source_el is not None else ""
        published = ""
        pub = (item.findtext("pubDate") or "").strip()
        if pub:
            try:
                published = email.utils.parsedate_to_datetime(pub).date().isoformat()
            except (ValueError, TypeError, OverflowError):
                published = ""
        out.append({"title": title, "publisher": publisher,
                    "url": url, "published": published})
    return out


def filter_window(items, report_date, days=WINDOW_DAYS, cap=MAX_ROWS):
    """Items published within ±days of the report date, newest
    first, capped. An item with no parseable published date is
    dropped — the window cannot be verified for it."""
    try:
        ref = date.fromisoformat(report_date)
    except (ValueError, TypeError):
        return []
    lo = ref - timedelta(days=days)
    hi = ref + timedelta(days=days)
    kept = []
    for it in items or []:
        try:
            d = date.fromisoformat((it or {}).get("published") or "")
        except ValueError:
            continue
        if lo <= d <= hi:
            kept.append(it)
    kept.sort(key=lambda it: it.get("published") or "", reverse=True)
    return kept[:cap]


async def news_for_ticker(ticker, fetch_text=_afetch_text, fetch_json=_afetch_json):
    """{ticker, report_date, news} for the /news route. Only a
    bad ticker raises ValueError (the route turns it into a
    400); every other failure degrades to an empty list and
    the card hides."""
    from .history import TICKER_RE
    t = (ticker or "").strip().upper()
    if not TICKER_RE.match(t):
        raise ValueError(f"Invalid ticker for news fetch: {ticker!r}")
    report_date = await report_date_for_ticker(t, fetch_json)
    if not report_date:
        return {"ticker": t, "report_date": None, "news": []}
    try:
        xml = await fetch_text(RSS_URL.format(ticker=t), headers=NASDAQ_HEADERS)
    except Exception:
        return {"ticker": t, "report_date": report_date, "news": []}
    return {"ticker": t, "report_date": report_date,
            "news": filter_window(parse_rss_items(xml), report_date)}
