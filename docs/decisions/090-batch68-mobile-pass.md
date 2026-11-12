# ADR 090 — Batch 68: Feature 10 mobile layout pass

## Status
Accepted. Built and tested Nov 12, 2026. Not yet pushed — rides with
Wave-3 (Batch 67) once the Wave-2 watch reports.

## Context
Tej opened the site on his phone and asked why it is not mobile
responsive. The honest answer: the mobile layout pass (Feature 10 of
the overnight spec) was sequenced deliberately LAST (Phase 6), after
every feature card was built, so it would not have to be redone after
each new card — and it never happened. What existed was piecemeal:
the viewport meta, the three-column layout stacking at 1180px,
tables scrolling inside their cards, the search row wrapping, the
hero and Discover grids stacking, the month-grid pills collapsing
to dots at 560px, and the week view stacking its day columns at
900px. What was missing was the coherent pass the spec defines:
search stacking, ≥44px tap targets, the Analyst table's first
column sticking while the rest scrolls, the claim popover expanding
in-flow instead of floating off-screen, and the guarantee of no
horizontal page scroll at widths ≥320px.

Two verification limits are real and must not be papered over:
the cloud browser cannot be resized to phone width (its viewport
stays 1919px; devtools/zoom shortcuts do not change it), and there
is no headless Chromium on the VM. So the spec's rendered checks
at 360/390/430px and 844px landscape are OWED — the final check
is Tej's phone after the push. What was verified instead: a static
CSS audit of every rule plus a JS test of the popover move
(harness `~/workspace/overnight-probes/mobile_pass_harness.js`,
39/39), and the full Python suite (363 passed, 1 skipped).

## Decision
Implement Feature 10 as specced, in `web/styles.css` plus one small
JS branch (see the deviation below):

1. **1180px rail order** — search card (already above the layout)
   → main column → right rail (charts) → left rail (handover
   detail). Was main → left → right. The conductor strip already
   lives inside `#agents` in the main column, so run progress stays
   visible above the briefing on mobile.
2. **<560px search row stacks** — input full width, Search button
   full width.
3. **≥44px tap targets** — `.btn-secondary`, `.chip`,
   `.analyst-filter`, `.analyst-sort`, `.chart-switch-btn`,
   `.cal-nav-btn`, `.cal-today-btn`, `.cal-view-btn`,
   `.wk-nav-btn`, `.wk-today-btn`, `.cal-more`, `.cal-entry`,
   and the popover close button. `min-height` beats the fixed
   28/30/36px heights set above without touching desktop. The
   week-view tiles were already 52px. Month-grid entries at 44px
   make busy month cells taller — accepted; the spec's rule, and
   the week view is the default.
4. **Analyst table sticky first column** — `th:first-child` /
   `td:first-child` get `position: sticky; left: 0` with an opaque
   `var(--card)` background and a 1px border shadow, inside the
   existing `overflow-x: auto` wrap. Scrolled content never shows
   through the stuck column.
5. **Claim popover becomes an in-flow detail** — at <560px the
   CSS makes it `position: static; width: 100%` with no shadow,
   and `openPopover` moves it under the table (claim rows) or
   right after the anchor (inline glossary terms) and clears the
   inline top/left. On desktop the branch re-appends it to the
   article before positioning, restoring it after a mobile open.
6. **Nav rows wrap** — `.wk-nav` and `.cal-nav` get `flex-wrap:
   wrap`; the week title drops to 15px at <560px. (The Batch 67
   week header — long title plus nav buttons plus the toggle —
   would otherwise overflow at 390px.)
7. **Baton rail scrolls internally** (`overflow-x: auto`) rather
   than forcing the page sideways.
8. **Story text wraps** — `overflow-wrap: break-word` on
   `.story p/li` so long URLs cannot overflow a card.

No content is hidden on mobile; the left rail is reordered, not
removed. Dark mode is untouched — every new rule uses theme
tokens, and the sticky column's background is `var(--card)`.

## Deviation from the spec (recorded, not hidden)
The spec says "web/styles.css only (no DOM moves, so desktop is
untouched)". A CSS-only popover cannot become a row detail: with
`position: static` alone it would land at the end of the briefing
article, far from the tapped claim. So the move is done in JS
(`openPopover`, ~14 lines): insert after the table wrap for claim
rows, after the anchor for inline anchors. Desktop behaviour is
unchanged (the branch only runs under the 560px media query, and
the desktop path re-appends the shared element to the article).

## Consequences
- The site gets its first coherent mobile pass; the remaining
  proof is a rendered check on a real phone after the push.
- The Wave-2 watch's Pages fingerprint counts the obsolete
  `renderCalendarStrip` marker (Batch 66 renamed the renderer to
  `renderCalendarGrid`), so its fingerprint check fails even
  though the code is live — the marker must be updated to
  `renderCalendarGrid` before the next watch run. The route
  probes in the watch are unaffected.
- Wave-3 now carries Batches 67 + 68: 11 files (the Batch 67
  manifest's `web/app.js` and `web/styles.css` now include the
  Batch 68 changes, plus this ADR).
