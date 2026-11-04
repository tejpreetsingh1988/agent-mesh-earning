# ADR 029 — Recent briefings strip (local cache)

Date: 2026-11-04
Status: implemented locally, upload + live verification pending

## Idea

Repeat visitors re-run the same companies. The cache from Batch 2
already saves every finished briefing in this browser's localStorage
(`ame_briefing_<TICKER>_<QUARTER|LATEST>`, plus the pre-quarter legacy
key), but the only way back to one was to search the company again
and let the cache banner appear. A "Recent briefings" strip under the
search box makes saved briefings one tap away.

## Decision (frontend only)

- A strip inside the search card, below "Most searched", listing up
  to 8 saved briefings, newest first: `{TICKER} · {quarter_label}`.
- Clicking a chip restores through the normal cache path
  (`getBriefing(ticker, quarter)`): instant render, saved-time banner,
  Refresh available. It never re-runs the pipeline and never writes a
  search-log row — reopening a briefing is not a search, so it must
  not feed "most searched".
- The strip refreshes on page load and after every fresh briefing
  saves (stream and POST paths), so a just-finished briefing appears
  immediately.
- A Clear button removes only `ame_briefing_*` keys and hides the
  strip. It touches no server data (there is none — the cache is
  local-only) and leaves the currently displayed briefing on screen.
- Corrupt entries and non-cache keys are skipped, never fatal.
  Legacy keys (no quarter segment) restore as latest, reusing the
  Batch 7 fallback.

## What this does NOT do

- No server history, no account, no sync: a different browser or a
  cleared store means an empty strip. That is the honest scope of a
  localStorage feature.
- No shareable history link — that is the compare-share batch, not
  this one.

## Verification

- `node --check web/app.js` clean.
- Node harness `/tmp/b11_harness.js` (fake DOM + fake localStorage):
  10 checks pass — empty store hides the strip, newest-first order,
  quarter labels, broken/unrelated keys skipped, chip data attributes
  (ticker + quarter, legacy → empty quarter), Clear wipes only cache
  keys and re-hides the strip, list caps at 8.
- Live verification pending: upload, then a browser check that a
  saved briefing appears in the strip and restores instantly on click.

## Addendum — Clear fix (found live, same day)

Live verification passed the strip, instant restore, and new-entry
cases, but Clear failed: the keys were deleted, yet the chips,
heading, and Clear button stayed on screen — and after reload the
empty heading + button still showed. Root cause: the strip's
`display: flex` author rule beats the browser's built-in `[hidden]`
rule, so setting `hidden = true` did not hide anything; the stale
chips were also never cleared. Fix: the empty path now clears
`chips.innerHTML` as well as hiding, and styles.css gains an explicit
`.recent-searches[hidden], .quarter-picker[hidden] { display: none; }`
rule (the quarter picker shares the same latent defect: it also uses
`display: flex` + the `hidden` attribute). Harness extended to 11
checks (stale chips removed). Re-verification of Clear pending.
