# ADR 035 — Print stylesheet

## Status
Accepted Nov 4, 2026 (Batch 17 of the product sweep).

## Context
A briefing is a record worth keeping, but printing the page
printed the whole app: search box, rails, workflow cards, and
buttons. Worse, printing from dark mode risked light text on
white paper, because the dark overrides survive into print
unless explicitly countered.

## Decision
- A single `@media print` block (styles.css only, no JS):
  hides the particle field, search card, compare box, both
  rails, agent/log/error sections, briefing actions, quarter
  picker, theme toggle, and cache banner; collapses the
  3-column grid to one column; drops card shadows; hides the
  hero subtitle and steps while keeping the eyebrow and
  title as the document heading. The briefing article, any
  comparison, and the footer disclaimer print.
- Dark mode is forced back to light tokens in print via
  `html[data-theme="dark"]` (higher specificity than the
  screen `[data-theme="dark"]` block), and the dark text
  overrides for story/pass/fail/alert copy are re-overridden
  to their light values, so nothing prints as light gray on
  white.
- No `print-color-adjust: exact` — browsers' default
  background stripping is what keeps the printout clean.

## Consequences
- No new UI and no behaviour change on screen; the only
  observable difference is the printout.
- Any future screen-only element must join the print hide
  list, or it will print — the harness checks the known set.
