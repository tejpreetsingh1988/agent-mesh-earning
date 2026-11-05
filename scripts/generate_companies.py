#!/usr/bin/env python3
"""Generate the browsable company directory under web/companies/.

Each company gets one short page whose first lines name the company
and its ticker in plain text. These pages serve two purposes: a
human-browsable directory, and the crawlable content for the AI
Search web-crawler instance (ticker resolution for the search box).
A page is short on purpose, so the crawler indexes it as a single
chunk that always contains the ticker.

To grow the directory, add {"name", "ticker"} rows to
web/companies/companies.json and re-run this script.

The script also writes web/sitemap.xml (directory URLs only —
the search box searches the company directory, not the briefing
UI) and web/robots.txt pointing at it. The sitemap exists
because the AI Search Discover crawl could not reach the
directory from the site root even after the homepage linked to
it (Nov 2, 2026: re-sync still indexed 0 documents), so the
instance uses Sitemap parsing instead, with the sitemap as the
exact URL list. Clean /companies/<TICKER> URLs are listed, not
the .html files (Pages redirects .html to clean and serves the
same content there).
"""
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "web" / "companies" / "companies.json"

# Canonical host for share/preview URLs (Feature 23). The sitemap
# itself deliberately stays on the OLD host (see base below):
# the AI Search instance crawls that host's sitemap, and
# recreating the instance would reset its allowlist. robots.txt
# may point at a sitemap on another host, so its Sitemap line
# uses the canonical host while the sitemap file keeps the old
# host's URLs.
CANONICAL = "https://earningsbrief.pages.dev"

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name} ({ticker}) — Earnings Ledger</title>
{og_tags}<link rel="stylesheet" href="../styles.css">
</head>
<body>
<main class="container">
  <h1>{name} ({ticker})</h1>
  <p>Ticker: {ticker}. Company: {name}.</p>
{note_line}  <p>Get the latest earnings briefing for {name} ({ticker}): verified
  revenue, margins, and earnings-per-share from SEC filings, checked
  by the Critic agent before the story is written. US large-cap,
  most recent reported quarter.</p>
  <p><a href="../index.html">Back to Earnings Ledger</a></p>
</main>
</body>
</html>
"""

INDEX_HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Company directory — Earnings Ledger</title>
<link rel="stylesheet" href="../styles.css">
</head>
<body>
<main class="container">
  <h1>Company directory</h1>
  <p>US large-caps with earnings briefings on Earnings Ledger. Search by
  company name on the home page, or pick a company below.</p>
  <ul>
"""

INDEX_TAIL = """  </ul>
</main>
</body>
</html>
"""


def main() -> int:
    companies = json.loads(DATA.read_text())
    seen = set()
    for c in companies:
        ticker = c["ticker"].strip().upper()
        if not ticker or ticker in seen:
            print(f"skipping duplicate/empty ticker: {c!r}", file=sys.stderr)
            continue
        seen.add(ticker)
        name = (c.get("name") or "").strip()
        # Feature 23: OG tags carry identity only, never a result
        # or verdict. A row with no name gets no OG tags rather
        # than a broken title. Names are HTML-escaped in the
        # attribute values (9 rows contain "&", e.g. JPMorgan
        # Chase & Co.); the visible title/h1 keep their bytes.
        og_tags = ""
        if name:
            esc = html.escape(name, quote=True)
            og_tags = (
                f'<meta property="og:title" content="{ticker} — {esc} | Earnings Ledger">\n'
                f'<meta property="og:description" content="Verified earnings briefings for {esc} ({ticker}) — every number traces to an SEC filing.">\n'
                f'<meta property="og:url" content="{CANONICAL}/companies/{ticker}.html">\n'
                '<meta property="og:type" content="website">\n'
                '<meta name="twitter:card" content="summary">\n'
            )
        note = c.get("note", "").strip()
        note_line = f"  <p>{note}</p>\n" if note else ""
        page = PAGE.format(name=name or c.get("name", ""), ticker=ticker,
                           og_tags=og_tags, note_line=note_line)
        (ROOT / "web" / "companies" / f"{ticker}.html").write_text(page)
    links = "\n".join(
        f'    <li><a href="{c["ticker"].strip().upper()}.html">'
        f"{c['name']} ({c['ticker'].strip().upper()})</a></li>"
        for c in companies
        if c["ticker"].strip().upper() in seen
    )
    (ROOT / "web" / "companies" / "index.html").write_text(
        INDEX_HEAD + links + "\n" + INDEX_TAIL
    )
    base = "https://agent-mesh-earnings.pages.dev"
    urls = [f"{base}/companies/"] + [
        f"{base}/companies/{c['ticker'].strip().upper()}"
        for c in companies
        if c["ticker"].strip().upper() in seen
    ]
    sitemap = ('<?xml version="1.0" encoding="UTF-8"?>\n'
               '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
               + "".join(f"  <url><loc>{u}</loc></url>\n" for u in urls)
               + "</urlset>\n")
    (ROOT / "web" / "sitemap.xml").write_text(sitemap)
    # Feature 23: robots.txt points at the canonical host's
    # sitemap; the sitemap file itself keeps the old host's URLs
    # (the AI Search crawl source — see CANONICAL above).
    (ROOT / "web" / "robots.txt").write_text(
        "User-agent: *\nAllow: /\n\n"
        f"Sitemap: {CANONICAL}/sitemap.xml\n"
    )
    print(f"generated {len(seen)} company pages + index + sitemap ({len(urls)} urls)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
