# ADR 066 — Batch 44: Feature 14 dividend card, data leg

Date: 2026-11-05. Status: data leg + frontend card built, tested,
live-probed (data leg); the route (`GET /dividends`) lands in the
follow-up batch, after Batch 43 pushes (the route edit touches
the Orchestrator's worker_main, Batch 43's file). The frontend
card is already built: a `#chart-dividend-card` section between
the long-series card and the glance card, rendered by
`renderDividends(ticker)` (same hide-on-failure + stale-ticker
pattern as the filings/trend cards), called from the briefing
render. Harness `~/workspace/overnight-probes/dividend_harness.js`:
**10/10 PASS** (payer rows + yield + next ex-date, non-payer
hides, fetch failure hides, yield hides without a close, stale
resolve dropped).

## Source verification (live probe, 2026-11-05)

Nasdaq `GET /api/quote/{T}/dividends?assetclass=stocks`
answers `{data: {dividends: {rows: [{exOrEffDate, type, amount,
declarationDate, recordDate, paymentDate, currency}]}}}`.
MSFT: 55 rows; first row is a declared FUTURE ex-date
(11/19/2026, $0.98); last 4 past Cash dividends are all $0.91
(08/20, 05/21, 02/19/2026, 11/20/2025). GOOGL pays now ($0.22)
so it is NOT a non-payer; BROS pays nothing (hide-card case).

## Change

New `mesh/dividends.py` (async, reusing the history module's
`_money`, `_parse_date`, `NASDAQ_HEADERS` and its dividends
endpoint):
- `select_dividends(rows, today)` — Cash-only, past (<= today,
  most recent first, take 4) vs future (earliest is the next
  declared ex-date); unparseable ex-date/amount rows dropped.
- `trailing_yield(last4, last_close)` — sum/close*100, 1
  decimal; None when the close or any amount is missing (the
  yield line hides, rows still show).
- `dividends_for_ticker(ticker, fetch_json, today)` — fetches
  dividend rows + recent closes in parallel; either failing
  degrades to its hiding state, never an exception; bad ticker
  raises ValueError.

## Live proof (module run against the real endpoints)

- MSFT: 4 rows (all $0.91), next ex-date 11/19/2026 $0.98,
  last close $493.95, trailing yield **0.7%** ($3.64 / $493.95
  = 0.737%, hand-checked).
- BROS: empty rows, yield None — the card hides, as specified.

## Tests

- 7 new unit tests (future ex-date excluded + reported as
  next; yield arithmetic on the real MSFT rows; Cash-only
  filtering; unparseable rows dropped; yield hides without a
  close; fake-fetch payload; bad ticker raises; fetch failure
  hides).
- Full suite: **282 passed, 1 skipped** (was 275).
