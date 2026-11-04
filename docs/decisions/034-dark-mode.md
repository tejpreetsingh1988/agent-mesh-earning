# ADR 034 — Dark mode

## Status
Accepted Nov 4, 2026 (Batch 16 of the product sweep).

## Context
The stylesheet was already fully tokenized (`:root` vars from the
shadcn/ui zinc rebuild), so a dark theme needed no restructure —
only a second token set, overrides for the colours the light
theme hardcodes, and chart colours, which canvas cannot resolve
from CSS variables.

## Decision
- A `[data-theme="dark"]` block redefines the tokens (zinc dark:
  near-black background, dark cards, lightened agent accents).
  Hardcoded light colours get explicit dark overrides: story
  and subtitle text, the primary-button hover, baton-node text,
  loop-leg background, alert and pass/fail text, status pills
  (including the agent-tint working pills), and the cache
  banner. Chart-card top borders and metric dots keep their
  mid-tone colours, which read on both backgrounds.
- A "Dark mode" / "Light mode" toggle sits in the header row
  next to the eyebrow. Choice persists in localStorage
  (`ame_theme`); with no stored choice the OS
  `prefers-color-scheme` setting applies.
- A 6-line inline script in `<head>`, before the stylesheet
  link, sets `data-theme` before first paint, so a returning
  dark-mode visitor never flashes light.
- Charts follow the theme in JS: a `themeColor(light, dark)`
  helper picks dark bar variants from `data-theme` at the four
  chart call sites, `Chart.defaults` tick/grid colours switch,
  and toggling re-renders any drawn charts via
  `updateAllCharts`. Toggling with no briefing drawn is a
  no-op for charts.
- The favicon (dark square, white check) is unchanged — it
  reads on both page themes and in the browser chrome.

## Consequences
- No backend change; the theme is a pure presentation
  preference and cannot affect any verified number.
- Any future hardcoded colour must gain a dark override, or it
  will ship light-only — the harness checks the known set.
