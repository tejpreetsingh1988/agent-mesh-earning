# ADR 044 — Visual business-model diagrams ("How it makes money")

## Decision
Every briefing gets a visual explanation of what the
company does and how it makes money — a diagram, not
a paragraph. "All visuals, no text" is read as
visual-first: icons + 1–3-word node labels + 2–4-word
edge labels, zero paragraphs. A diagram with
literally no labels is unreadable (a box that says
nothing means nothing), so labels stay but prose goes.

## Grammar (fixed, same for every company)
- Roles: Payer (who pays), User (who uses),
  Company (center), Partner/Channel (distributes).
  One small inline-SVG icon per role, drawn once,
  reused everywhere — no generated images, no
  AI-image slop, no hallucinated text inside images.
- Edges: money = solid green arrow (pays), value =
  dashed zinc arrow (provides / uses). Two arrow
  types, one tiny legend.
- Layout (deterministic, no LLM layout): Payers
  left, Company center, Users right; money flows
  payer → company, value flows company → user.
  Two-sided models fall out naturally: Snap has
  advertisers on the left paying and users on the
  right using free, with attention flowing back to
  advertisers. Loops (Roblox: players pay → Roblox
  → creators → experiences → players) render as a
  return edge underneath.
- No widths-as-data: flows are uniform. A wider
  pipe would claim a revenue share, and segment
  shares are not in the pack (segment facts are
  unbuilt). Uniform flows, labeled streams, never
  an invented proportion.

## Generation (spec, not image)
- The LLM produces a JSON spec — nodes {id,
  label, role, icon}, edges {from, to, kind,
  label} — from grounded text: the earnings
  release's About paragraph + highlights, fetched
  by the KPI batch's exhibit 99.1 work (ADR 043).
  The KPI extraction and the diagram spec come
  from ONE shared LLM call: no extra call, no extra
  cost.
- The frontend renders SVG deterministically from
  the spec (column assignment by role, curve
  routing). Same grammar + same renderer = every
  company looks like it came from one designer.
- Spec validation: ≤8 nodes, ≤10 edges, labels
  ≤4 words, NO numbers anywhere in the diagram.
  Numbers stay in the verified claims table; the
  diagram shows structure only, so it cannot
  violate the verified-numbers rule.

## Honesty labeling
The diagram is structure, not verification: it is
labeled "Simplified model — illustrative, from the
company's earnings release", never presented as
Critic-verified. A wrong structure is possible
(the release's About text is short); the numbers
beside it are still verified, and the diagram never
carries a figure that could be wrong.

## Placement, caching, cost
- Section "How it makes money" in the briefing
  article, right after the verdict and before the
  claims — structure frames the numbers.
- Spec cached with the briefing (cache entry grows
  {briefing, facts} → {briefing, facts, diagram});
  a cached briefing restores its diagram instantly.
- No new vendor, no key, no extra LLM call beyond
  the shared KPI call. Section hides when no spec
  is produced (same graceful rule as KPIs).

## Directory consequences (checked Nov 4, 2026)
Of Tej's example list, FTNT, RBLX, CAVA, APP were
already in. SNAP, SEZL, CRDO, IREN were missing
but PASS the SEC admission test (recent 10-Q AND
10-K verified live) and are added here: 162 → 166
companies, 167 sitemap URLs, no churn on old
pages. ARM fails (20-F only, no 10-Q/10-K) and PSH
is absent from the SEC ticker map entirely (a
Guernsey fund listed in Amsterdam/London, not an
SEC registrant) — neither gets a briefing or a
diagram in v1. A standalone diagram mode (no
briefing attached) would be the route to those,
and is a later batch, not this one.

## Proof cases (when built)
FTNT, RBLX, CAVA, APP first, then SNAP, SEZL,
CRDO, IREN once the directory addition is live.

## Open at build time
Icon set (one inline SVG per role); column/curve
layout details; exact spec schema; whether the
spec extraction shares the KPI call's prompt or
runs as a second output block of it.

## Implementation notes (Batch 23, built Nov 4, 2026)
- Shared call, second output block: the KPI
  prompt (`mesh/kpi.py::kpi_prompt`) now also asks
  for a "diagram" object; one reply carries both.
  `parse_kpi_response` returns (items, diagram,
  parsed-ok); `_settle_reply` settles the reply
  when valid KPIs OR a valid diagram exist, or
  when it parses cleanly to nothing (stop the
  chain); garbled or fully-invalid replies try the
  next model. `extract_kpis_*` return
  (items, diagram); `kpis_for_pack_*` return
  (items, diagram, source_url). Schema: Briefing
  gains `diagram: dict | None`; `write_briefing`
  passes it through from kpi_result; both Writer
  handlers (sync `agents/writer/main.py`, proof
  via the sync-script transform) unpack the
  triple.
- Layout settled: three columns — left x=110
  holds payers AND partners (partners stack below
  payers; both are supply side), center x=300 is
  the company, right x=490 is users. Node = icon
  circle (r=17) + label below, never a text box,
  so long labels cannot overflow. Same-column
  edges bow left (clear of labels); left→right
  edges bow gently up; right→left return edges
  bow deep underneath. Colors are CSS variables
  (--green, --muted-foreground, --card, --border,
  --foreground), so the diagram follows light/dark
  mode with no re-render and no new CSS.
- Icon set settled (stroke glyphs, one per role):
  payer = coin circle + bar; user = head + shoulders
  arc; company = building outline + midline;
  partner = two overlapping circles. The spec's
  icon field is accepted and dropped — the role
  fixes the glyph, so the model cannot invent icon
  names. Role alias: "partner-channel" → "partner".
- Validation settled (`validate_diagram`): invalid
  nodes/edges drop (with their dependents); nodes
  truncate to 8, edges to 10; node labels 1–3
  words, edge labels ≤4 words (empty edge labels
  allowed); any digit in any label drops that
  node/edge; result must have ≥2 nodes, ≥1 edge,
  exactly one company node, else no diagram.
- Cache correction: no cache-shape change was
  needed — the diagram rides inside the briefing
  object, which the cache already stores, so a
  cached briefing restores its diagram instantly.
  Placement: the section sits after Takeaways
  (still after the verdict, before the claims).
  The .md export renders diagram edges as text
  lines (it cannot carry SVG usefully).
- Grounding check: BROS's About paragraph sits
  14% through its release text, inside the 20,000-
  char prompt window — no tail-window games
  needed. Live LLM diagram output is NOT yet run
  (mocked-model tests only); proof cases FTNT,
  RBLX, CAVA, APP await upload + live
  verification, as do SNAP/SEZL/CRDO/IREN (their
  directory pages are in the held bundle).
- Tests: `tests/unit/test_diagram.py` (8 tests);
  KPI tests updated for the tuple/triple returns
  (17 tests); frontend harness
  `/tmp/b23_harness.js` 13/13; full suite 186
  passed, 1 skipped on two consecutive runs (one
  transient failure on the first post-sync run,
  test not captured — treated as flake, not a
  defect, since the reruns are green). Upload +
  live verification join the held bundle behind
  the Batch 20 verification report.
