# ADR 072 — Batch 50: Feature 18 3-way compare

Date: 2026-11-05. Status: built + harness-tested; live check
waits on the next Pages deploy (frontend-only, no Worker
change).

## Change

The comparison is now N-way (2 or 3 companies):
- `alignClaims(...claimLists)` is variadic; rows carry a
  `values` array, one per briefing, with "—" for a metric a
  briefing doesn't have. `compareTableHtml(tickers, rows)`
  takes the tickers array. `renderComparison` is now a thin
  wrapper over `renderComparisonN(briefings, opts)`, which
  renders the verdict cards, headline table, full claims table,
  units block, and growth race for N briefings.
- The 3-way title is the three tickers, nothing more — no
  overall verdict, no ranking, no "best" column. The quarters
  line names every quarter and warns when they differ.
- The compare box gains an "Add a third company" button after
  the second company is picked (hidden for same-ticker
  compares); it reveals a second picker using the same
  directory matcher, whose picks go to `startCompare3`. The
  third briefing runs sequentially after the 2-way comparison
  (base, then second, then third — no parallel pipeline runs).
  A failed third briefing falls back to the completed 2-way
  comparison with a note naming the failed ticker; it never
  shows a partial third column. A duplicate third (base or
  second ticker) is refused inline.
- Removing the third: a "Remove" button on the third verdict
  card re-renders the 2-way view and drops `compare2` from the
  share link; the "Add a third company" button reappears.
- Share link: the 3-way run writes
  `?ticker=<BASE>&compare=<SECOND>&compare2=<THIRD>`
  (+ `&quarter=` for the base quarter); a fresh 2-way run
  deletes `compare2`. `parseShareLink` parses `compare2` only
  when it differs from both companies already in the
  comparison; the load path chains it via
  `pendingThirdCompare`, consumed in the 2-way onDone.
- `renderUnitEconomics(tickers)` is N-way: one line per
  company, "—" for a company missing an input, and the block
  still renders when at least two companies have values (for
  the 2-way case that is the same as before: both must have
  values). `renderGrowthRace` was already N-ready and receives
  the tickers array.

## Tests

- Harness `~/workspace/overnight-probes/three_way_compare_harness.js`:
  **21/21 PASS** (N-way alignment with "—"; 3-way title and
  quarters line; three verdict cards and columns; growth race
  called with 3 tickers; third box hidden on 3-way; Remove
  returns to the 2-way title and drops compare2; failed third
  keeps the 2-way view with a note naming the ticker;
  duplicate third refused and runs nothing; compare2 parses,
  invalid third dropped, 2-way link has no third; units block
  shows "—" for the missing company with 2 of 3 values and
  hides with fewer than 2). Two harness bugs found along the
  way (a duplicated `let lastComparison` across overlapping
  extraction slices; a missing `ORCHESTRATOR_URL` stub that
  made the units fetch fail before being called) — both
  harness-side, not app code.
- Feature 17 harness re-run after the aligner refactor:
  **19/19 PASS** (no regression).
- `node --check web/app.js` clean.
- Live check (MSFT vs GOOGL vs NVDA — three columns, growth
  race draws all three lines, share link restores the trio)
  waits on the Pages deploy.
