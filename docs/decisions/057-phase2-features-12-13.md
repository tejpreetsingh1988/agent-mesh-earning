# ADR 057 — Phase 2: Recent filings card (Feature 12) + Quarter trend table (Feature 13)

Date: 2026-11-05. Status: built + tested; live verification pending.

## Feature 12 — Recent filings card

- New module `mesh/filings.py`. Pure picker `pick_recent_filings(cik, recent)`
  selects the newest **1 × 10-K, 3 × 10-Q, 5 × 8-K** from the SEC
  submissions `recent` block (parallel arrays, newest first); document
  URLs are built with the Archives pattern
  `https://www.sec.gov/Archives/edgar/data/<cik>/<accession-no-dashes>/<primaryDocument>`,
  never guessed from another pattern.
- `fetch_recent_filings_async(ticker)` reuses the existing CIK mapping
  (`async_get_company_facts`) and submissions fetch (`_submissions`)
  from `mesh/async_tools.py`, so the Batch 35 retry in the shared
  transport applies. It never raises — a failed fetch returns an error
  payload and the frontend hides the card.
- New Orchestrator route `GET /filings?ticker=X` in
  `apps/orchestrator/worker_main.py` (same pattern as `/history`).
  `filings.py` was added to the orchestrator vendor list in
  `scripts/sync-worker-proof.py`.
- The card is metadata + links only and never says what a filing
  contains. An 8-K is listed as an 8-K — never labelled "earnings"
  (the quarter's earnings 8-K is identified by the Scout, not here).
- Frontend: `<section class="card" id="sec-filings">` after Sources,
  before Data notes. `renderFilings(ticker)` is fire-and-forget like
  ownership: rows merged across forms, newest filing date first, each
  row `FORM · report <date> · filed <date> — Open filing`. Hides on
  fetch failure, error payload, or zero rows. Stale-guard on
  `lastBriefing.ticker` like `renderHistory`.

## Feature 13 — Quarter trend table

- Backend: `gaap_eps` added to `QUARTERLY_METRICS` and
  `METRIC_LABELS` in `mesh/history.py` — an allow-list extension only;
  the GAAP EPS tag path already existed in the Scout's quarterly
  facts (values are raw USD per share, not scaled to billions).
  The existing `GET /history` route serves the series.
- Frontend: `<section class="card" id="sec-trend-table">` after
  Verified claims, before "What drove the quarter". `renderTrendTable`
  fetches three history series in parallel (`total_revenue`,
  `gaap_eps`, `operating_income`) and aligns them by `period_end`
  with the pure helper `trendTableRows` (harness-tested):
  newest first, max 8 rows; margin = operating income / revenue per
  shared period only; QoQ = (current − prior) / prior for consecutive
  revenue quarters only — the prior quarter must be 70–110 days
  earlier, otherwise the cell is "—". A missing quarter is "—",
  never interpolated or carried forward. The whole card hides if any
  fetch fails; a metric missing for a quarter shows "—" for that
  cell and the other columns still render.
- Footer line, verbatim: "From SEC filing facts via the history
  series. — means the quarter is not in the fetched series."
- The table reuses the existing `.table-wrap` (horizontal scroll on
  narrow screens) and generic `table` styles — no new CSS.

## Verification

- `tests/unit/test_filings.py` — 6 tests (URL builder, 1/3/5 limits
  on an interleaved fixture, short feed, empty feed, async fetch
  with fake transport, never-raises). `tests/unit/test_history.py`
  gains a gaap_eps test (allow-list + series values verbatim).
  Full suite: 259 passed, 1 skipped.
- `~/workspace/overnight-probes/phase2_harness.js` — 12/12 PASS
  (alignment, margin per shared period, missing EPS, QoQ math,
  gap rule, 8-row cap, empty/single-quarter).
- Live check pending: MSFT briefing — filings card lists the
  newest 1/3/5 with working SEC links and matching dates; trend
  table revenue/margin match the claims table's latest quarter;
  QoQ arithmetic spot-checked on two adjacent quarters.
  Composition check C2 (spec appendix): the trend table's EPS
  column must match the Scout's quarterly facts for the latest
  quarter — if not, the EPS column ships as "—" until fixed.

## Not built in this batch

- Features 14 (dividend card), 15 (shareholder yield), 16
  (cash-return chart), 22 (fiscal calendar note) — specced in
  `docs/overnight-features-spec.md`, not yet built.
