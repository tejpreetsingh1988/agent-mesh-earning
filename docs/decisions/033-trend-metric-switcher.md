# ADR 033 — Trend chart metric switcher

## Status
Accepted Nov 4, 2026 (Batch 15 of the product sweep).

## Context
The quarter-trend chart showed revenue only, although Scout
already collects operating income for the same quarters
(`pivotFacts` orders `total_revenue`, `operating_income`,
`gaap_eps`). A second metric needed no new pipeline call — only
a way to pick which held series the chart draws.

## Decision
- The trend card gains a small segmented switcher: Revenue /
  Operating income. Switching re-renders only the trend chart
  from `lastScoutFacts`; it never triggers a briefing run.
- `updateTrendChart` is parameterized by a module-level
  `trendMetric` (default `total_revenue`). The chart label and
  the empty note follow the chosen metric ("No operating income
  series in this briefing's facts."), so a briefing without that
  series states the gap instead of silently falling back.
- The choice persists across briefings in the session: it is a
  viewing preference, not per-briefing state. A new briefing
  re-renders the trend card with the chosen metric (or its empty
  note) via the existing `updateAllCharts` path.
- No other chart changes: growth, EPS, and margin cards keep
  their claim-derived series.

## Consequences
- Zero backend or Worker change; the switcher is frontend-only
  and cannot invent a number — it draws only held Scout facts.
- If a future metric is added to the switcher, it needs a
  `pivotFacts` series and a label branch, nothing else.
