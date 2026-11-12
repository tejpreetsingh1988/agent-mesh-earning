# ADR 082 — Batch 60: visual-check fixes (Discover hole, dark-mode pills)

## Status
Accepted — Nov 12, 2026. Built, tested, not yet pushed (folds into the
follow-up push with Batch 61).

## Context
The live visual check of Batch 59 (browser task, Nov 12, 09:30–09:32 PST)
passed the hero and the volume bar but found two real defects:
1. A fresh browser has no cached briefings, so `renderRecentBriefings`
   hid its card and the 3-column Discover grid showed two cards plus
   a large empty third column.
2. The baton-rail agent pills (`.loop-leg`) never set a text colour, so
   in dark mode they fell back to the UA `ButtonText` (black) on the
   dark pill — "Analyst", "Critic" and "Writer" nearly invisible.
The same check also noted the "Recent searches" chips showing raw
logged fragments ("crwv", "applov", "cloud", "Bros"). That is the log's
real data (chips have no truncation rules), not a rendering bug — no
change. "Calendar unavailable" in the same check was the Orchestrator
Worker still serving the pre-push build (new routes 404 at the time),
not a UI bug.

## Decision
- **Discover grid (styles.css):** `repeat(3, 1fr)` becomes
  `repeat(auto-fit, minmax(280px, 1fr))`, so a hidden card can never
  leave an empty track.
- **Your briefings always shows (app.js):** `renderRecentBriefings`
  renders an empty state ("No saved briefings yet — run one and it
  will appear here.", `.disc-empty`) with count "0" instead of hiding
  the card. The shared `count` element is now declared once at the
  top of the function.
- **Dark-mode pills (styles.css):** `.loop-leg` gets
  `color: var(--foreground)`. Auditing the same hardcoded-colour
  family found the Analyst filter's active state (white text on a
  near-white `--primary` pill in dark mode — invisible) and the
  filter/sort controls' hardcoded white backgrounds; all three get
  dark-mode token overrides.

## Consequences
- No behaviour change beyond the empty state: same fetch calls, same
  click handlers, same IDs. Clear now shows the empty state instead
  of hiding the card.
- Verification: `node --check` clean (one duplicate-`count`
  declaration caught and fixed during the build); discover harness
  updated for the empty state, **24/24 PASS**; full suite pending.
- The mobile (~390px) stacking check could not be done by the
  browser task (no viewport resize available); the 900px/560px
  breakpoints exist in CSS but remain unverified live.
