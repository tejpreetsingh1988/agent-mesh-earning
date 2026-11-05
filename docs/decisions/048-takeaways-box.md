# ADR 048 — Takeaways box (Batch 29)

A box at the top of the briefing (after the
verdict, before the claims table) with at most
four bullets, chosen deterministically from the
briefing's own verified claims and drivers:

1. Biggest YoY growth move (largest |value|
   among "YoY growth" claims, sign preserved).
2. Operating margin claim, if present.
3. EPS vs consensus claim, if present.
4. First driver, if any.

Rules that keep it honest:

- Claim texts are reused verbatim — they are
  already complete sentences with periods and
  values. Nothing is reworded, so no new number
  can enter through this box.
- YoY only for the growth pick. QoQ is the same
  metric measured twice and would double-count
  it.
- Missing items are skipped, never filled in;
  the section hides when there is nothing to
  show. The verdict itself is NOT repeated as a
  bullet — it sits directly above the box.
- No new model call, no new cost, no new CSS
  (reuses `.card` / `.list`). Pure function
  `takeawaysFor(b)` in web/app.js, wired into
  render().
- Unlike the Batch 19 checked line, takeaways
  need no fresh run: a cache restore recomputes
  the same bullets from the stored briefing, so
  they show on restores too.
- UI-only in v1: the .md download export is
  unchanged (it already contains the verdict and
  the full claims; takeaways add selection, not
  information).

Verification: harness /tmp/b29_harness.js 13/13
(full / partial / empty / QoQ-only / negative-
biggest / driver-cap cases + static checks);
app.js syntax-checked; full Python suite still
161 passed, 1 skipped (frontend-only change).
Upload + live verification join the held bundle
behind the Batch 20 verification report.
