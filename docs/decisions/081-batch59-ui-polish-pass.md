# ADR 081 — Batch 59: UI polish pass (cards, colour, tags)

## Status
Accepted — Nov 12, 2026. Built, tested, not yet pushed (folds into the
pending 51–55+58 push; see below).

## Context
Tej: "clean up the UI into cards and much more readable with colors and
tags. Recently searched and Search Volume bar is also not clean — this is
not how big companies do UI....Fix everything end to end."
The site had drifted into the "quiet zinc" direction: monochrome cards,
flat 1px borders, and the search card's three discovery rows (Recent
briefings / Recent searches / Most searched) as bare grey labels + plain
chips. The "Most searched" row — the search-volume indicator — showed
volume only as "×N" text on chips, with no ranking and no bar.
Also found during the build: the 51–55+58 push never landed — remote main
is still at d4fbdb74 (Nov 5), so this batch builds on local-only code and
folds into the same push.

## Decision
- **Card system (styles.css):** semantic tokens (`--success/--warning/
  --info` + bg/border, `--shadow-sm/md`, dark variants); `.card` gets
  the shadow token; a shared `.card-head` pattern (title + subtitle +
  right-aligned tag); `.tag` pills in teal/blue/amber/violet/green/red/
  gray, always paired with text (colour is never the only signal).
- **Discover zone (index.html + app.js + styles.css):** the search
  card's three flat rows become three real mini-cards in a 3-column
  grid — Your briefings (logo chips + quarter tags + count tag +
  Clear), Recent searches (logo chips + ticker tags), Most searched
  (a true volume bar: rank, query, bar sized to the top query's
  count, count). All element IDs unchanged; the wrappers lost the
  `.recent-searches` class, so `.discover-card[hidden]` hides them.
  The grid hides itself when all three cards are hidden
  (`:has(> :not([hidden]))`; unsupported browsers leave a 16px gap).
- **Hero steps (styles.css only):** the four steps become mini-cards,
  numbered by CSS counter and coloured per agent (teal/blue/amber/
  violet). No HTML change; the old `→` separator is overridden.
- **End to end (styles.css only):** briefing section titles get a
  divider; chart cards get a coloured dot before the title matching
  their top accent; At a glance becomes label-above-value stat tiles;
  calendar days become tiles; search input no longer uppercases typed
  text; `:focus-visible` outline everywhere (Feature 9c, brought
  forward — cheap, and the right moment).
- **Dark mode / print / responsive:** dark tokens + tag variants for
  every new colour; discover grid and step cards stack at 900px,
  step cards to one column at 560px; the discover zone hides in
  print with the search card, hero steps already did.

## Consequences
- No behaviour change: same fetch calls, same click handlers, same
  IDs. The volume bar is display-only (bar width = count / max).
- `renderMostSearched` now renders `.vol-row` buttons instead of
  `.chip.search-match`; the click selector changed with it.
- Verification: `node --check` clean; HTML tag balance clean; CSS
  braces/parens balanced; new harness
  `overnight-probes/discover_harness.js` **23/23 PASS** (dedupes,
  logos, tags, bar widths 100/75/25, clicks, Clear, empty state);
  the other 8 app.js-slicing harnesses re-run green (85 checks);
  full suite **327 passed, 1 skipped**.
- The one thing no harness can prove: how it *looks*. The live
  visual check runs after the push, via the browser on the live
  site (light + dark, desktop + narrow).
- Specificity traps found and fixed in the build: `.card-muted`
  needed its `box-shadow: none` re-asserted after the `.card`
  shadow rule, and `.glance div:last-child` needed its border and
  padding re-asserted — both old rules outrank the new ones.
