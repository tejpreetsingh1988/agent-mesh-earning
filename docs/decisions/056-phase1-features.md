# ADR 056 — Overnight features Phase 1 (Features 1–8)

Date: 2026-11-05
Status: Accepted (code complete + harness-verified; upload pending)
Context: The overnight spec's Phase 1 (Features 1, 6, 2, 3, 7, 5,
4, 8) — claim popover, copy-claim, glossary, find, page title,
keyboard shortcuts, explainer card, did-you-mean. All frontend
only (web/app.js, web/index.html, web/styles.css); no backend,
no new fetch, no new dependency.

## Decisions

- **Popover replaces the inline formula-row expansion.**
  `analystTableHtml` no longer renders `formula-row` rows and
  `analystExpanded` state is gone. A row click opens ONE shared
  `<div id="claim-popover">` appended to `#briefing` (which is
  now `position: relative`), positioned below the clicked row.
  The popover is a trace, not a second verification: it shows
  the display derivation (stripped + rounded, exactly as the
  table shows it) and deterministically matched source lines.
- **Raw derivations are kept in `lastAnalystClaims`.**
  `render()` no longer strips the ", from facts …" suffix when
  building `briefingClaims`; `parseClaim` still strips it for
  display. The popover's matcher needs the raw derivation (the
  fact ids are embedded in it).
- **Facts are stored per table, not per module.**
  `renderAnalyst` takes a `facts` param, stored in
  `analystTableFacts[key]`; filter/sort re-renders reuse it. A
  comparison run overwrites the module-level `lastScoutFacts`
  with the second company's facts — the base table must never
  cite the wrong filing. The find box uses `renderFacts`,
  snapshotted in `render()` for the same reason.
- **Source matching is exact, never a guess.** Fact-id
  substring match on the raw derivation first; else a period
  fallback usable only when all matching facts share one
  metric; otherwise the fallback line ("See Sources section
  below"). The market-reaction claim matches nothing — the
  fallback line is its correct outcome.
- **Glossary is one dict, one popover.** `GLOSSARY` (8 terms,
  exact spec wording) is the single source: claim rows and the
  verdict get first-occurrence buttons per render, and the
  footer link renders the same text as a list section.
- **Copy-claim format is byte-exact per spec**, with the
  provenance line from the table's own context (ticker +
  quarter stored per table in `analystTableContext`); the
  clipboard fallback is the same textarea/execCommand pattern
  as the comparison-share button.
- **Find counts data, navigates DOM.** The count is the pure
  `countFindMatches` over claims/facts/story; navigation steps
  through claim rows, story `<mark>`s, then the Sources section.
  Clearing unwraps marks exactly (text restored byte-identical).
  KPIs, diagram, fine print, ownership and comparison are never
  searched.
- **Keyboard: `/` focuses search, `Esc` closes one layer per
  press** (popover → search results → compare results); `/`
  never fires from inside a field and never inserts a `/`.
- **Explainer is first-visit only** (`ame_explainer_dismissed`
  in localStorage); the footer re-show link never touches the
  briefing cache.

## Verification

- Node harness `~/workspace/overnight-probes/phase1_harness.js`:
  30/30 pass (source matching incl. derived-Q4 form, copy text
  byte-exact, glossary rules, Levenshtein + did-you-mean incl.
  the "Krogr" → KR case, find counts incl. the hand-counted
  "revenue" = 11).
- Live checks per each spec's test plan remain (upload first):
  popover source lines on a fresh MSFT briefing + cache
  restore; copy-paste; each glossary term + footer list;
  find "margin" stepping; title on render/quarter switch/
  comparison; keyboard walkthrough; explainer first-visit +
  dismiss + re-show; "Krogr" → KR.
