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

## Verification fix (Nov 4, 2026 — after the first live
## verification FAILED)

The first live verification (NVDA, earningsbrief.pages.dev)
showed the picker but every fiscal click fell back to the
latest quarter with "Unrecognized quarter label", and no
consensus. Diagnosis, in order:

1. The frontend HAD shipped (fiscal buttons rendered), and
   the Scout HAD received the fiscal label (it quoted it in
   the note) — so the deployed Scout Worker was serving
   pre-Batch-20 code. The local repo and proof copies were
   both already fixed and identical; the Workers Build for
   the Batch 20 scout commit had not produced a live
   deployment. The re-upload below doubles as the fresh
   build that unsticks it (same remedy as the Nov 2 Critic
   stale-serving incident: a never-built commit).
2. A real code gap Batch 20 missed: `mesh/scout_async.py`
   — the cloud path — hand-mirrors the consensus guard
   with an EXACT-date comparison (`cons_end !=
   requested_end`) while the sync guard went
   month-granular. Its module docstring claimed quarter
   logic is imported so fixes land in both paths at once;
   that was false for this guard. Fixed to
   `_same_fiscal_month` (imported from scout.py), docstring
   corrected, and a regression test added
   (`test_async_fiscal_quarter_keeps_month_granularity_consensus`:
   April row "Apr/2026" → month-end 2026-04-30 vs actual
   end 2026-04-26 must be kept). Without this fix, the
   April briefing would still have lost its consensus even
   after the redeploy.
3. A second frontend gap in the same class: the page-load
   auto-run pre-filtered `?quarter=` to calendar labels
   only, so a shared fiscal link (or a reload) dropped the
   quarter and restored the latest briefing. Fixed by
   passing the parameter through and letting
   `getBriefing`'s own validation (which accepts fiscal
   labels) decide.

Open after this fix (observed, not part of it): the live
NVDA picker showed Apr/Oct/Jul 2025 but no Jan 2026, though
the picker logic itself is correct (distinct fact periods <
current, newest first). The likely cause is a facts gap, not
a picker bug: on the cloud path facts are EDGAR-only, and
NVDA's Jan-2026 (Q4 FY2026) row depends on the derived-Q4
reconstruction from the 10-K. To confirm on re-verification
by inspecting the latest briefing's fact periods; if Jan
2026 is still absent, it is a separate EDGAR-derivation
follow-up, not a quarter-switching failure.
