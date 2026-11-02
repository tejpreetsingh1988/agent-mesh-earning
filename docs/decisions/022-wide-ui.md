# ADR 022 — Wide, dynamic UI: handover loop, Analyst table, charts (Nov 2, 2026)

## What changed
- `web/` rebuilt from the 880px single column to a 1440px 3-column shell:
  left = live agent-handover loop rail, centre = agent cards + briefing,
  right = charts + at-a-glance rail. Below 1180px the rails stack
  under the centre, in reading order.
- Analyst claim cards replaced with a real table (Analyst card AND
  briefing "Verified claims"): Metric | Period | Result pill | Detail,
  with filter chips (All / Growth / Margin / EPS / Price / Other),
  sort (original / biggest % / Metric A–Z), and click-a-row to expand
  the exact derivation. The table parses metric/period/detail out of
  the claim text for display only; the result pill is the Analyst's
  own `value`, rounded as before. Nothing is recomputed in the browser.
- Charts (right rail) are drawn only from streamed data:
  quarter trend = Scout `total_revenue` facts; growth = Analyst YoY
  claims; EPS vs consensus = the Analyst claim's `$X vs $Y` detail;
  operating margin = the Analyst margin claim as a doughnut.
  A chart with no source data stays empty with placeholder text.
- Handover loop (left rail): an SVG pentagon Scout → Analyst →
  Critic → Writer → Conductor, with two packets circling on
  `animateMotion` and a dashed gradient path. `setLoop()` follows
  SSE events: the active node glows, earlier nodes are marked done,
  and a handover feed logs e.g. "Scout → Analyst: 24 facts".
  Loop legend / nodes click through to the matching agent card.
- Background: tsParticles slim bundle (MIT, ~8.9k stars, maintained
  successor to particles.js) over a CSS mesh of blurred teal/blue/
  violet/amber blobs. If the CDN is blocked, the CSS mesh still
  shows and the briefing never depends on the background library.
  `prefers-reduced-motion` skips particles and blob animation.
- Charts: Chart.js (MIT, ~67.7k stars, v4.5.1 via CDN). If it fails
  to load, tables still show every number; charts stay empty.
- Design direction for this pass (user, Nov 2): more colour, more
  motion, more interactivity, use the blank left/right sides —
  landing-page inspiration (land-book, recent.design, landdding,
  rainbrand). This supersedes the muted zinc look for the Pages
  site only; the numbers, agents, and stream contract are unchanged.
  All existing element IDs used by `app.js` are preserved.

## Verification (Nov 2, local only)
- `node --check web/app.js` passes.
- Local `python -m http.server` served index/app/styles at 200.
- `parseClaim()` tested in Node against the MA Q3 2026 screenshot
  claims: Revenue YoY +14.0% ($8.6B → $9.8B), Operating margin
  59.8%, EPS vs consensus +3.3% ($5.31 vs $5.14), GAAP EPS QoQ
  +6.2% — all parse to the correct metric / period / detail.
- Both CDN URLs returned 200 on Nov 2:
  tsparticles-slim@2.12.0 and chart.js@4.5.1.

## Deployment status: NOT LIVE
- `web/` is untracked in the local repo and the local repo is
  diverged (see MEMORY lesson: any future PC push needs a fresh
  clone first; VM git-push auth failure is parked).
- Do NOT push from this VM. Copy `web/` into a fresh clone on
  the PC, commit, and push to main — Cloudflare Pages
  (agent-mesh-earnings, output `web/`) auto-deploys on push.
- After deploy, verify live by running a briefing (e.g. MA) and
  checking: loop nodes light in order, Analyst table filters/sorts,
  and all three charts fill from that run's data.
