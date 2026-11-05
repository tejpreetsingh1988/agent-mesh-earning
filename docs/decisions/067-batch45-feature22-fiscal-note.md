# ADR 067 — Batch 45: Feature 22 fiscal calendar note

Date: 2026-11-05. Status: built + harness-tested; ships with
the next Pages deploy (frontend-only, no Worker change).

## Change

A `<p class="meta" id="fiscal-note">` directly under the
quarter picker, rendered by `renderFiscalNote()` (called from
`renderQuarterPicker`, so it runs on fresh runs and cache
restores alike). `fiscalNoteMonths(facts)` takes the distinct
`period` values from the briefing's own Scout facts, keeps the
last 8, and returns their distinct months in calendar order as
abbreviated names. Fewer than 4 distinct fact periods hides
the note. Text: "Quarter ends in the latest facts fall in:
Jan, Apr, Jul, Oct." — observed months only; it never states
a future quarter-end date and never "corrects" an irregular
52/53-week calendar.

Built out of order (the spec puts 22 last in Phase 2) because
it has no dependency on Features 14/15/16 — it reads only the
facts already on the page — while 15 needs the /dividends
route that is still pending.

## Tests

- Harness `~/workspace/overnight-probes/fiscal_note_harness.js`:
  **6/6 PASS** (NVDA months in calendar order; 3 periods hides;
  irregular months as observed; 9th period ignored; duplicate
  metrics deduped).
- `node --check web/app.js` clean.
- Live check (NVDA briefing shows its observed months) waits
  on the next Pages deploy.
