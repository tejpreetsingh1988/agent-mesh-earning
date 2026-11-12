# ADR 077 — Batch 55: Feature 24 news around earnings

Date: 2026-11-05. Status: built + tested locally; push HELD
with Batches 51–54 until after Tej's EPAM interview
(11:30 AM–12:00 PM PT).

## Change

- `mesh/news_rss.py` (new): `parse_rss_items` (stdlib
  xml.etree over the Google News RSS document; `<source>`
  text is the publisher, `<pubDate>` becomes an ISO date,
  an item without a title or URL is dropped),
  `filter_window` (±7 days around the report date, newest
  first, cap 10; an unparseable published date is dropped),
  and `news_for_ticker` (async). The source is the
  V3-verified Google News RSS endpoint (no key, 87 items
  for MSFT in the probe); the URL stays Google's redirect
  link — v1 does NOT resolve it to the publisher's
  canonical URL and must not claim to. yfinance is not
  used (confirmed unusable on the Worker path).
- The report date comes from a new public helper in
  `mesh/past_reactions.py`, `report_date_for_ticker` (the
  latest quarter's earnings 8-K filing date — the same
  identification the Scout used), because the Briefing
  schema does not carry it. A missing report date, a failed
  feed, or nothing in the window degrades to an empty list
  and the card hides (hide-on-failure; Worker-side
  fetchability is the one unproven leg, and the first live
  run is its proof). Only a bad ticker raises ValueError.
- `GET /news` in `apps/orchestrator/worker_main.py`,
  mirroring the `/dividends` route. Sync script's
  Orchestrator module list gains `news_rss.py` (proof copy
  verified byte-identical).
- Frontend card `#sec-news` in `web/index.html`, after the
  Recent filings card and before Data notes, rendered by
  `renderNews(ticker)` following the renderFilings pattern.
  Rows: headline (linked to the redirect URL), publisher,
  published date (ISO). The mandatory footer line is in
  the HTML. Headlines are never cited as briefing sources
  and no number is pulled from one.
- `tests/unit/test_news_rss.py` (8 tests) +
  `tests/unit/test_news_rss_route.py` (2 tests).

## Tests

- Data-leg + route + past-reactions tests: **20 passed**.
- Harness `~/workspace/overnight-probes/news_harness.js`:
  **6/6 PASS**.
- `node --check web/app.js` clean.
- Live check (a briefing's news card shows only in-window
  headlines with working publisher links; hides for a
  briefing whose window has no headlines; the first live
  run also proves Worker-side fetchability) waits on the
  push after the EPAM interview.
