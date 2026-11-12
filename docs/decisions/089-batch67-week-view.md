# ADR 089 — Batch 67: TipRanks-style week view for the reporting calendar

## Status
Accepted — Nov 12, 2026. Built, tested, not yet pushed (Wave-3
candidate; Wave-2's watch was still running when this was
built).

## Context
Tej sent a photo of TipRanks' "This Week's Earnings" card and
said: "Take this as a sample for design. Improve it 10x."
The sample: a dark card, one column per weekday, each day
split into a sun half (before open) and a moon half (after
close), every entry a big logo tile with its ticker above it.
Batch 66's month grid (a cell per day, pills on entries) is
correct but visually flat next to it — the timing is a label
on the entry instead of the structure of the day.

## Decision
1. **The week view is now the default.** A dark panel in both
   themes (near-black `#101013`, white text, orange day
   headers — the sample's look, deliberately a feature panel
   rather than a themed card). Five weekday columns, Mon–Fri;
   each day splits into ☀ Before open and 🌙 After close
   halves, and every entry is a 52px logo tile on white with
   its ticker above it. Clicking a tile runs the briefing.
2. **Timing is structure, not a label.** Rows with no Nasdaq
   timing land in a "Time TBA" foot row under their day —
   never guessed into a half. Saturday/Sunday reporters appear
   in a weekend strip below the grid, only when there are any.
   A failed day is marked "Unavailable" in its column. Today
   gets an amber header. On ≤900px the day columns stack.
3. **"Most anticipated" is not copied.** That is TipRanks'
   ranking and we have no such data — the panel shows the
   directory companies reporting that week, with no ranking
   invented. The header says "This week · Nov 16 – Nov 20,
   2026" and the card sub stays "Nasdaq earnings calendar".
4. **The month grid survives** behind a Week/Month toggle in
   both views' nav rows (its legend moved into the month
   render, since the week view's sun/moon headers are
   self-explanatory). Backend: `GET /calendar?week=YYYY-MM-DD`
   returns the Monday–Sunday week containing that date
   (`calendar_for_week_of`, Monday-anchored); the no-param
   default stays the current month, so the Wave-2 watch's
   calendar check is unaffected.

## Consequences
- Tests: `monday_of` (Thu/Sun/Mon inputs), `calendar_for_
  week_of` (Nov 16 week, NVDA after-hours, failed Saturday),
  route `?week=` / week-wins-over-month / invalid-week
  fallback. Harness `calendar_week_harness.js` 9/9 (sun/moon
  split, TBA row, weekend strip, today, shifting, tiles);
  the month-grid harness needed a slice fix after the Batch 67
  block moved the `renderCalendarGrid();` call — it now slices
  to the Batch 67 comment and stubs the shared toggle
  helpers. Full suite 363 passed, 1 skipped.
- Live proof owed after the push: the week panel renders the
  current week with NVDA on Tue Nov 17 under the moon half,
  and the Month toggle still shows the Batch 66 grid.
- Note: an `muse.edit` with a non-unique `renderCalendarGrid();`
  anchor replaced the wrong occurrence mid-file and mangled
  app.js; repaired by replacing the whole calendar section
  (lines 3279–3487) in one Python span write and re-checking
  with `node --check`. Lesson: anchors must be unique or the
  edit goes through the span-write path.
