# ADR 040 — Quarter picker for non-calendar fiscal companies

## Status
Accepted Nov 4, 2026 (Batch 20 of the product sweep).

## Context
The Batch 7 quarter picker only worked for calendar
companies: it derived previous quarters from the label
("Q3 2026" → Q2, Q1, Q4), so a fiscal label like
"quarter ended 2026-07-26" (Nvidia, Costco, Apple)
parsed to nothing and the picker hid itself. Fiscal
companies are a large share of the directory, so the
picker's absence there was a visible gap, not an edge.

## Decision
Backend (`mesh/scout.py`, vendored into the scout
Worker proof by the sync script):
- `_quarter_end_from_label` now also accepts the fiscal
  fallback label: "quarter ended 2026-07-26" →
  "2026-07-26" (validated as a real date). The whole
  Batch 7 requested-quarter flow — 8-K selection in the
  75-day window, facts truncated to the quarter end,
  NOT_REPORTED_YET when nothing matches — then works
  unchanged for fiscal quarters.
- Two exact-date comparisons that silently broke fiscal
  quarters now compare fiscal months instead, via a
  shared `_same_fiscal_month` helper: Nasdaq reports a
  fiscal quarter as month/year, so its month-end
  (2026-07-31) and a fiscal actual end (2026-07-26)
  are the same quarter. This fixes (a) the filing
  confirmation in `_pick_quarter_filing` — without it,
  a fiscal quarter fell back to the earliest in-window
  8-K with a "could not confirm" note — and (b) the
  consensus guard, which discarded the consensus row
  for every fiscal quarter and would have left the
  beat/miss badge and EPS chart empty. Month
  granularity is backward compatible: calendar
  quarters confirm exactly as before (their month-end
  IS the quarter end), and a different month still
  mismatches.
- No orchestrator change: it passes `quarter`
  through opaquely. Only a docstring mentions fiscal
  labels now.

Frontend (`web/app.js`):
- `getBriefing` accepts fiscal labels alongside
  "Qn YYYY" (previously it stripped anything else to
  latest, so even a shared fiscal link silently ran
  the latest quarter).
- `renderQuarterPicker` gains a fiscal branch:
  previous quarters come from the briefing's own
  Scout facts — real period ends, newest first,
  excluding the current quarter, max 3 — because
  fiscal calendars are irregular (52/53-week years,
  Sunday/Saturday ends) and date arithmetic would
  invent quarter ends. Buttons show the short label
  ("Jul 2026") but carry the full fiscal label.
  Calendar companies keep the existing computed
  path unchanged. The facts are available on both
  paths: stream runs set `lastScoutFacts` from Scout
  events, cache restores set it from the saved entry.
- A fiscal picker shows only quarters that exist in
  the facts — never a dead click — unlike the
  calendar path, which can offer an unreported
  quarter that returns NOT_REPORTED_YET.

## Consequences
- The picker now appears for fiscal companies on
  both fresh runs and cached briefings.
- A fiscal quarter briefing keeps its consensus
  comparison (beat/miss, badge, EPS chart), which
  the old exact-date guard would have dropped.
- The 75-day 8-K window and 50-filing limit from
  Batch 7 still bound old fiscal quarters the same
  way they bound old calendar ones.
