# ADR 091 — Batch 69: cache-busting asset URLs

## Status
Accepted. Built and tested Nov 12, 2026. Not yet pushed — rides with
Wave-4, after the Wave-3 watch reports (never push during a watch).

## Context
Tej's screenshot of the new week view (Nov 12, ~11:30 PST) looked
broken: a light panel instead of the dark one, days stacked, the
sun/moon labels and tiles inline on the same row, "Time TBA" inline
at the left of the tiles, content-sized tiles (LCID much wider than
the rest), tickers wrapping below their logos.

The code was not at fault. The served files were verified
byte-identical to local (styles.css 52,802 B, app.js 187,391 B),
the stylesheet parses cleanly (braces 507/507, no unclosed
comment), and every `.wk-*` rule is present and correct. What
Tej's browser rendered was the NEW app.js (it renders the week
view, which only exists in Wave-3) against a CACHED pre-Wave-3
styles.css (which has no `.wk-*` rules at all). Every symptom in
the screenshot is exactly what unstyled week-view HTML looks
like: default button borders, block-stacked days, inline label
+ tiles in each half, inline TBA label, tiles sized by their logo
content.

Root cause: `web/index.html` referenced bare `styles.css` and
`app.js` with no versioning, so a returning browser was free to
serve the old stylesheet with the new script.

## Decision
`scripts/stamp-assets.py` rewrites the three same-origin asset
references in `web/index.html` to content-hash URLs:
`styles.css?v=<sha256[:8]>`, `app.js?v=<sha256[:8]>`,
`favicon.svg?v=<sha256[:8]>`. A changed file gets a new URL, so
the browser always fetches the matching JS/CSS pair; an unchanged
file keeps its cached copy. The script is idempotent (re-running
with unchanged files leaves index.html byte-identical) and runs
before every push. `tests/unit/test_asset_cache_busting.py`
enforces it: each stamp must equal the file's current hash, and
no bare href/src reference may remain. The watch script's
fingerprint curls `app.js` without a query — the file still
exists at that URL — so it is unaffected. External assets
(Google Fonts, Parqet logos) are not stamped.

## Consequences
- Returning visitors can never again get a mismatched JS/CSS
  pair after a push.
- Immediate relief for Tej is a hard refresh (Cmd+Shift+R /
  Ctrl+Shift+R), which revalidates the cached stylesheet — the
  week view then renders as designed (dark panel, five columns,
  52px tiles). The stamp only takes effect after the Wave-4 push.
- Wave-4 files: `web/index.html` (stamped URLs),
  `scripts/stamp-assets.py`, `tests/unit/test_asset_cache_busting.py`,
  this ADR. The push procedure gains a step: run the stamp script
  before building the manifest; the suite fails if the stamps are
  stale.
