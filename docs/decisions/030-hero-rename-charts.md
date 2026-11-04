# ADR 030 — Hero redesign, rename to Earnings Ledger, favicon, progressive charts

## Context

The top of the page was the weakest part of the product. A screenshot
review (Nov 4, 2026) showed: a gradient wordmark and gradient button
plus pastel blobs (the AI-slop look the project bans); an eyebrow
claiming a "LIVE AGENT LOOP" after Batch 9 replaced the loop with a
straight baton rail; subtitle copy pointing at "the loop on the left"
and "charts on the right" (layout-dependent copy that breaks on
mobile); four pastel pills that looked clickable but did nothing; a
four-line hint explaining AI Search mechanics; and, on first load,
four blank chart cards plus a glance row of dashes. The product name
itself, "Agent Mesh", describes the architecture, not what the visitor
gets. The visitor gets a checked record of earnings numbers — a
ledger.

## Decision

**Rename the product to Earnings Ledger.** The URL move is a separate
batch (Batch 13): a new Pages project, AI Search host/sitemap
migration, then the export footer. This batch renames everything
in-site; the old URL keeps serving until Batch 13 lands.

**Hero, rewritten (web/index.html, web/styles.css):**

- Eyebrow: the agent chain only, `SCOUT → ANALYST → CRITIC →
  WRITER`, in muted zinc. No "LIVE" (nothing is live until a run
  starts), no loop language.
- Wordmark: `Earnings Ledger`, all ink, no gradient. The `.grad-text`
  rule is deleted.
- Subtitle: "Pick a company. Four agents find the filing, compute
  the numbers, re-check every one, and only then write the story.
  Nothing publishes without the Critic's pass." No references to
  left/right layout.
- The four pills become one ordered line, `.hero-steps`: Scout finds
  the filing → Analyst computes growth and margins → Critic re-checks
  every number → Writer writes only what passed. Arrows carry the
  order; nothing pretends to be clickable. The `.hero-chip` and
  `.chip-*` rules are deleted (they were used only here).
- Search button: solid ink (`var(--primary)`), not the blue→violet
  gradient. It is the only `.btn-primary` on the page.
- Pastel blobs: the `.bg-blobs` div and all `.blob` CSS are deleted.
  The particle field stays (motion remains) but is recoloured to
  monochrome zinc (`#a1a1aa` dots, `#d4d4d8` links) in
  `initBackground`.
- Hint: one line — "Search 109 large-cap companies by name or ticker
  — pick a match and its briefing runs. Every number traces to a
  filing." The directory link is kept. NOTE: the "109" count must be
  updated whenever the directory grows.
- Strip order: Recent briefings first, then Recent searches, then
  Most searched. Your own briefings are the most useful shortcut.
- Briefing chips shorten fiscal labels: `shortQuarterLabel` turns
  "quarter ended 2026-08-30" into "Aug 2026" for chips only; the
  briefing itself and the saved-time banner keep the full label.
- Footer credit drops "over a CSS mesh" (the blobs are gone).
- Chart headings drop their emoji (📊📈🎯); the rail was the last
  emoji carrier in the layout.

**Favicon (web/favicon.svg):** a dark rounded square (`#18181b`) with
a bold white check. At 16px it reads as "verified" — the brand in one
glyph. Linked from index.html as an SVG icon. No PNG/apple-touch
variant in this batch.

**Company pages:** `scripts/generate_companies.py` brand strings
changed and the generator re-run: all 109 company pages plus the
directory index now read "Earnings Ledger" (verified: 110 files
carry it, 0 still carry "Agent Mesh").

**Charts reveal progressively (the first-load complaint):**

- The right rail now holds one quiet card on first load,
  `#charts-empty-state` ("Charts live here — run a briefing and
  charts fill from the same numbers…"). No blank chart cards, no
  dash rows.
- `setChartsVisible()` (web/app.js) toggles `has-facts` /
  `has-claims` on `#charts-rail` from `lastScoutFacts` /
  `lastAnalystClaims`. CSS shows the trend card only with facts,
  growth / EPS / glance only with claims, and hides the empty-state
  card as soon as either exists.
- Wired into `updateTrendChart` (scout_done path), `updateAllCharts`
  (analyst_done / render / cache paths), and `clearCharts` (a new
  run hides everything again, so the rail is honest mid-run too).
- Per-chart empty notes now say what is actually missing when their
  card shows without data ("No revenue series in this briefing's
  facts.", "No YoY claims in this briefing.") instead of "Run a
  briefing…" while a briefing is running.
- This is the same principle as Batch 9's ledger: show output as it
  arrives, never blank placeholders up front. The POST fallback
  keeps its existing shape (no streamed facts → trend stays hidden,
  claims cards show).

## Verification

- `node --check web/app.js` clean.
- Node harness `/tmp/b12_harness.js` (fake DOM + fake localStorage):
  9 checks pass — shortQuarterLabel cases (Aug 2026, Q3 passthrough,
  empty, Jan boundary), COST chip renders "Aug 2026", rail class
  transitions (clear → facts → claims → clear).
- Live verification pending: upload, then a browser check of the
  hero (new name, no gradient, steps line, solid button, favicon,
  strip order, shortened chip) and the rail (one note card on first
  load; trend appears at Scout, rest at Analyst).

## Out of scope (Batch 13)

- The Pages URL move (new project + AI Search host/sitemap
  migration + export footer domain). Until then the export footer
  still reads `agent-mesh-earnings.pages.dev` and the old URL serves
  the renamed site.
- Download filename is renamed in this batch
  (`Earnings-Ledger-<TICKER>-<quarter>.md`) since it is brand, not
  URL, and needs no migration.
