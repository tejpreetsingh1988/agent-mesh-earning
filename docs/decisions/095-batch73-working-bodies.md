# ADR 095 — Batch 73: working card bodies + an honest run estimate

## Status
Accepted. Built and tested Nov 12, 2026. Pushed in Wave-7.

## Context
The live visual check of Batch 72 (MSFT run, Nov 12) confirmed
the status line works — "Starting — Scout is first" →
"Now: Scout — fetching filings" → "Now: Writer — writing the
story" → "Done — briefing ready" — and finished stages read
clearly as green checks. It also found two contradictions:
1. While a step was Working, its card body still read
   "Queued — runs first / runs after …". The badge said Working,
   the body said Queued. Cause: `resetCards()` writes the Queued
   body text once, and the working transitions only ever changed
   the badge (`setStatus`) — the body was first replaced when the
   step finished.
2. The Scout detail promised "Usually 30–90s". Scout took 5.5s
   in that run and the Writer alone took 262s — the run as a
   whole took 270.9s. The estimate described neither the step
   nor the run. Observed runs span 44s (DUOL) to 271s (MSFT).

Two non-issues from the same check, recorded so they are not
re-litigated: the Analyst/Critic "Now:" lines flash by in under
a second (0.3s / 0.6s) because those stages genuinely are that
fast — the status line does show them, a person just cannot read
them live; and the conductor dot looked light grey in a still
screenshot because its amber pulse animation fades — the code
applies the amber `is-running` class correctly
(`.conductor-dot.is-running`, `#b45309`, 1.2s pulse); stills
cannot show a pulse.

## Decision
- Every working transition now sets a Working body alongside
  the badge: Scout "Working — fetching the earnings filing from
  SEC EDGAR…", Analyst "Working — checking the numbers against
  the filing…", Critic "Working — re-checking every claim…",
  Writer "Working — writing the story…", and on a Critic FAIL
  the Analyst body becomes "Working — revising the claims after
  Critic feedback…". New `.agent-working` style: full-contrast
  14px text (unlike the muted Queued grey), so a working card
  reads as live work at a glance.
- The estimate is now the whole run: "Whole run usually 1–5
  min" in the Scout detail and the run-start line. No per-step
  time promise is made anywhere.

## Consequences
- The harness gains Part 5: no "Usually 30–90s" string remains;
  each working branch sets its Working body; `.agent-working`
  exists in the stylesheet. Harness 149/149 (142 Batch 72 + 7
  Batch 73).
- Wave-7 files: `web/app.js`, `web/styles.css`,
  `web/index.html` (re-stamped), this ADR.
