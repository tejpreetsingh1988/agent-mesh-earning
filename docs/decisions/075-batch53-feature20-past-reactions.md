# ADR 075 — Batch 53: Feature 20 past earnings reactions

Date: 2026-11-05. Status: built + tested locally; push HELD
with Batches 51–52 until the Batch 43 rebuild watch lands.

## Change

- `mesh/past_reactions.py` (new): `quarter_ends_from_recent`
  (last 4 10-Q reportDates from the submissions feed, newest
  first — a 10-Q's reportDate IS its quarter end, so the route
  needs no briefing facts), `earnings_8k_candidates` (8-Ks
  filed in (quarter end, +75 days], earliest first), and
  `past_reactions_for_ticker` (async; identifies each quarter's
  earnings 8-K, fetches Nasdaq historical in the Batch 28
  window, and builds rows via `mesh/market.py::reaction_payload`
  — no new close logic).
- Identification reuses the KPI batch's rule with one
  deliberate difference: `fetch_release_text_async` takes only
  the single earliest 8-K in the window, but here the
  candidates are tried earliest-first until one's index lists
  an exhibit-99.1-shaped file, because the spec's rule is
  "the 8-K ... whose index lists" one — an earlier 8-K
  without a 99.1 must not block a later earnings 8-K. For the
  last 2 quarters of a test company the two agree; the C1
  composition check verifies that on the first live run.
- A quarter with no identifiable earnings 8-K (or no closes)
  is omitted and counted; a quarter with no close after the
  report date yet carries null close_after/change_pct (the UI
  renders "—"). Only a bad ticker raises ValueError.
- `GET /past-reactions` in `apps/orchestrator/worker_main.py`,
  mirroring the `/dividends` route. Sync script's Orchestrator
  module list gains `past_reactions.py` (proof copy verified
  byte-identical).
- Frontend card `#sec-past-reactions` in `web/index.html`,
  after the Market reaction section, rendered by
  `renderPastReactions(ticker)` following the renderFilings
  pattern. Columns: Quarter ended, Report date, Close before,
  Close after, Change %. Footer carries the Nasdaq caveat
  plus the omitted-quarters note. Fewer than 2 rows hides
  the card.
- `tests/unit/test_past_reactions.py` (10 tests) +
  `tests/unit/test_past_reactions_route.py` (2 tests).

## Tests

- Data-leg tests: **10 passed** (75-day window, 99.1 skip-to-next,
  GOOGL proven window 2026-10-28 → 2026-10-29 $324.89 → $283.82
  -12.6%, weekend Fri-base/Mon-reaction, missing-reaction null,
  omitted counting). Two test bugs found along the way (a window
  expectation that forgot the Nov 15 8-K; a Nasdaq fixture that
  only covered the latest quarter) — both test-side.
- Harness `~/workspace/overnight-probes/past_reactions_harness.js`:
  **7/7 PASS**.
- `node --check web/app.js` clean.
- Live check (C1: GOOGL table — most recent row's window
  matches the briefing's market-reaction section; the rule
  picks the same 8-K the Scout picked for the last 2
  quarters) waits on the push after the rebuild watch.
