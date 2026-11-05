# ADR 070 — Batch 48: Feature 19 growth race chart

Date: 2026-11-05. Status: built + harness-tested; live check
waits on the next Pages deploy (frontend-only, no Worker
change).

## Change

A `#growth-race-card` inside the comparison section, between
the headline table and the full claims table, rendered by
`renderGrowthRace([base, second])` (called from
`renderComparison`; the tickers array is N-ready for Feature
18's third company). `growthRaceData(seriesByTicker)`:
- Common window = the intersection of the companies' quarter
  periods (positive values only — a period where any value is
  non-positive is dropped, mirroring the Worker's rebase
  skip rule). Series are never shifted, stretched, or
  forward-filled.
- Each series is indexed to 100 at the first common quarter.
  The Worker's `rebase` gives % change from first (0 at
  start), so indexed = value_pct + 100 — same math, no new
  rebasing.
- Total growth = (last/first − 1) × 100 and CAGR =
  (last/first)^(365.25/days) − 1 over the common window,
  reusing the history module's formulas. Both appear in the
  legend ("MSFT (+11.6%, CAGR 15.9%)").
- Fewer than 4 common quarters: the chart hides and the card
  shows the note "Fewer than 4 common quarters — no indexed
  chart." Fetch failure hides the card; a superseded pair is
  dropped (`lastGrowthRacePair` guard).

## Consequence of the exact-period rule

The common window needs identical period_end dates, so two
companies on different fiscal calendars share no quarters at
all — MSFT (quarters end Mar/Jun/Sep/Dec) vs NVDA (Jan/Apr/
Jul/Oct) will show the note, never a chart. That is the spec
working as written (never shift or stretch to force a window),
but it means the chart only ever draws for companies whose
quarters actually coincide.

## Tests

- Harness `~/workspace/overnight-probes/growth_race_harness.js`:
  **20/20 PASS** (intersection, rebase to 100, total growth +
  CAGR hand-checked on the MSFT/GOOGL fixture, <4-quarter
  hide rule, non-positive period dropped, 2-line chart with
  growth in the legend, note shown on <4 quarters, fetch
  failure hides, superseded pair dropped).
- `node --check web/app.js` clean.
- Live check (a 2-way comparison with overlapping histories
  renders the chart; legend totals match hand-computed last ÷
  first − 1 from the trend tables) waits on the Pages deploy.
