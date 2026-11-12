# ADR 092 — Batch 70: the week-view CSS was trapped inside `@media print`

## Status
Accepted. Built and tested Nov 12, 2026. Pushed in Wave-4 with
Batch 69.

## Context
Tej's screenshots of the week view (Nov 12) showed it unstyled —
light panel, stacked days, inline labels and tiles, content-sized
tiles — and a hard refresh changed nothing. The first diagnosis
(stale cached stylesheet, ADR 091) was wrong: the served files
were byte-identical to local, the headers force revalidation
(`max-age=0, must-revalidate`), and a fresh cloud browser showed
the same broken layout.

The real cause was found by parsing the stylesheet with tinycss2:
the `@media print` block that opens at line 396 was never closed
before the calendar blocks were added, so **all 33 `.wk-*` rules
and the whole Batch 66 month-grid block sat inside `@media
print`** — print-only, never applied on screen, in any browser.
The file still parsed cleanly and the braces still balanced
(507/507), because the print block did close eventually (line
~496) — just 100 lines too late. The month grid was unstyled
since Batch 66 for the same reason; its earlier "cramped" report
was the same unstyled HTML misread as a layout quirk.

Why the fresh-browser check looked contradictory: its "dark
panel" was the dark-theme card background (that browser defaults
to dark theme), not the `.wk-panel` rule; the logo images
themselves carry white backgrounds, which read as "white tiles".

## Decision
Close `@media print` right after the genuine print rules (after
the `[data-theme="dark"] .story p` rule), freeing the Batch 66
month-grid and Batch 67 week-view blocks to top level. Reopen
`@media print` immediately before the dark-override group
(`[data-theme="dark"] .agent-pass` etc. plus `a { color:
inherit; }`), which the print comment says belongs there — those
rules re-override dark colours for printing and must stay
print-only, not leak onto the screen. Verified with tinycss2:
33 top-level `.wk-*` rules, the print blocks hold 7 + 4 rules
with zero calendar selectors, braces 508/508, zero parse errors.

## Consequences
- The week view and the month grid render as designed on screen
  for the first time; printing is unchanged (the print rules are
  intact, just split across two `@media print` blocks).
- New guard: `tests/unit/test_css_print_scope.py` — a
  dependency-free brace scanner asserting no calendar selector
  lives inside any `@media print` block, and at least 30
  top-level `.wk-` selectors exist. A future swallowed block
  fails the suite instead of shipping silently.
- Lesson (recorded for the next build): a clean parse and
  balanced braces prove nothing about scope — any CSS edit that
  touches a file with an `@media` block gets a scope check, and
  a fresh-browser visual check is the proof for a restyle, not
  file diffs. The earlier "stale cache" call was a misdiagnosis;
  the cache-busting in Batch 69 is still worth keeping (it
  prevents the same symptom class), but it was not the cause.
- Wave-4 files: `web/styles.css` (the fix),
  `tests/unit/test_css_print_scope.py`, this ADR — plus the
  Batch 69 files (`web/index.html` re-stamped, stamp script,
  cache-busting test, ADR 091).
