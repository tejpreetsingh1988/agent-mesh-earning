# ADR 088 — Batch 66: reporting calendar as a month grid

## Status
Accepted — Nov 12, 2026. Built, tested, not yet pushed (folds
into the Wave-2 push with Batches 61 + 64 + 65).

## Context
Tej: "reporting calendar should be in a calendar format, before
open, after open with the logo...currently its every messy".
The Feature 11 strip (Batch 54) was 7 dated rows of chips —
no report timing at all, and the backend dropped Nasdaq's
`time` field entirely.

## Decision
1. **The data already had the timing.** A live probe of the
   Nasdaq calendar (Nov 12–17, 2026) shows the `time` field is
   real and well-populated: `time-pre-market` (before market
   open), `time-after-hours` (after market close),
   `time-not-supplied` (unknown). Nov 12: 124 after-hours, 64
   pre-market, 162 not-supplied out of 350 rows; NVDA's Nov 17
   row is correctly `time-after-hours`. `parse_calendar_day`
   now maps the two real values to `"before"` / `"after"` and
   everything else to `None` — a row without timing gets no
   pill, never a guessed one.
2. **Month grid, not a strip.** `GET /calendar?month=YYYY-MM`
   returns every day of that month (`{month, days}`); missing
   or invalid month falls back to the current month, never an
   error. A month is ~30 Nasdaq calls, so they run under a
   semaphore (8 in flight) — the keyless endpoint is the shared
   rate limit. The frontend renders a real calendar: ‹ month ›
   navigation + Today, Sun–Sat weekday header, day cells with
   the date number (today highlighted), each entry a logo +
   ticker + timing pill (amber "Before open", blue "After
   close"), up to 3 entries per cell with a "+N more" expander,
   failed days marked "Unavailable" in-cell. Clicking an entry
   runs the briefing, as the chips did. Non-directory tickers
   are still dropped. On ≤560px the pills become colour dots
   (the legend under the grid explains them — colour is never
   the sole signal on desktop).
3. **Retired:** the 7-day strip renderer, its CSS, and the
   `calendar_for_week` route wiring (the function stays in the
   module, tested, for reuse). The watch script's calendar
   check moves from "7 days" to the month shape.

## Consequences
- Tests: `test_calendar.py` gains time-mapping, month-shape
  (November 2026: 30 days in order, NVDA after-hours, empty
  Sunday, failed day) and concurrency-cap tests; the route test
  pins month/default/invalid-month. Harness
  `calendar_grid_harness.js` 8/8 (Nov/Dec 2026 alignment,
  pills, +N more, error day, today, month shifting). Full
  suite 359 passed, 1 skipped.
- Live proof owed after the push: the grid renders November
  2026 with NVDA on the 17th carrying an "After close" pill,
  and month navigation loads December.
- Note for the record: the old strip test fixture used the
  invented value `"time-bmo"` — it never was a Nasdaq value
  and now maps to None like any unknown.
