# ADR 076 — Batch 54: Feature 11 earnings calendar strip

Date: 2026-11-05. Status: built + tested locally; push HELD
with Batches 51–53 until the Batch 43 rebuild watch lands.

## Change

- `mesh/calendar.py` (new): `parse_calendar_day` (the
  V1-verified Nasdaq shape — `{data: {asOf, headers, rows}}`,
  `rows: null` is an empty day, a row without a symbol is
  dropped; only symbol + name are used — no time, no
  estimate) and `calendar_for_week` (7 parallel day-fetches,
  today + 6, one day's failure never takes down the others;
  a failed day carries `error: true`).
- `GET /calendar` in `apps/orchestrator/worker_main.py` (no
  params, no 400 case — the calendar is global, not per
  ticker). Sync script's Orchestrator module list gains
  `calendar.py` (proof copy verified byte-identical).
- Frontend card `#calendar-strip` in `web/index.html`,
  directly below the search card and above `.layout`,
  rendered by `renderCalendarStrip()` on every load
  (after `loadDirectory`, reusing its directory cache).
  Seven rows (weekday + date), each listing that day's
  directory companies as chips in the suggestion chip
  style (logo + name + ticker); clicking a chip runs that
  company's latest briefing via `getBriefing`. The route
  returns every row and the frontend filters to directory
  tickers — the frontend already holds
  `web/companies/companies.json` for search, so no second
  copy of the directory is vendored into the Worker.
  Non-directory tickers are dropped silently; an empty day
  shows "No directory company scheduled"; a failed day
  shows "Calendar unavailable for this day"; a whole-fetch
  failure shows "Calendar unavailable — try again later."
  The footer caveat ("Expected report dates from the Nasdaq
  earnings calendar — dates can change.") is in the HTML.
- `web/styles.css`: `.calendar-row` / `.calendar-day` /
  `.calendar-chips` (day label + wrapping chips).
- `tests/unit/test_calendar.py` (5 tests) +
  `tests/unit/test_calendar_route.py` (1 test).

## Tests

- Data-leg + route tests: **6 passed**.
- Harness `~/workspace/overnight-probes/calendar_strip_harness.js`:
  **8/8 PASS** (7 dated rows, weekday labels, directory
  chips only, empty-day line, failed-day line, chip click
  runs the briefing). Two harness bugs found (the slice end
  marker matched an earlier keydown listener; the chip
  listener closed over the loop's `m`, which is null after
  the loop) — both harness-side, not app code.
- `node --check web/app.js` clean.
- Live check (strip shows 7 dated rows, every chip is a
  directory ticker, a failed day renders its unavailable
  line) waits on the push after the rebuild watch.

## Follow-up fix (same batch, found by the full suite)

The full suite failed at collection: the Orchestrator proof
tests load the proof worker, and `mesh/past_reactions.py`
imported `EDGAR_HEADERS` + `exhibit_991_candidates` from
`mesh/kpi.py` — which the Orchestrator proof does NOT vendor
(kpi.py pulls the LLM chain: gateway_binding, llm,
worker_ai). Fix: `EXHIBIT_991_RE`, `exhibit_991_candidates`,
and `EDGAR_HEADERS` moved to `mesh/edgar.py` (vendored in
every proof); `kpi.py` imports and re-exports them, so
fineprint and the kpi tests keep working unchanged, and
`past_reactions` now imports from `.edgar`. Proof copies
re-synced and verified byte-identical. Full suite after the
move: **312 passed, 1 skipped** (289 + 23 new tests).
