# ADR 084 — Batch 63: ticker search answers from the local directory first

## Status
Accepted — Nov 12, 2026. Built, tested, not yet pushed (folds into
the follow-up push with Batches 60/62 + CoreWeave).

## Context
Tej reported ticker search as "really slow". The cause was the
search path, not the network: every Search click / Enter went to
the Cloudflare AI Search LLM round trip first (seconds), and only
fell back to the local directory when the index found nothing —
while a `searching` lock froze the instant suggestions for the
whole wait. A ticker the local directory already holds never
needed the network at all, and a second Enter while a search was
in flight was silently dropped.

## Decision
- **Local first:** `searchCompanies` checks the directory
  (`localMatches`, substring on name/ticker, top 5) before any
  network call. A match renders immediately and skips AI Search
  entirely; the cache stores it the same way.
- **AI Search only on a local miss:** for fuzzy and
  description-based queries ("chip maker"), where the index can
  match page text the directory cannot. Zero-match AI results
  render the empty state with did-you-mean (the local directory
  was already checked, so there is no local fallback to offer).
- **No lock:** the `searching` flag is gone. A newer
  `searchCompanies` call aborts the in-flight AI fetch via
  AbortController (superseded calls stay silent); the AI fetch
  has an 8s timeout instead of hanging on "Searching…".
- **Instant suggestions unlocked:** the input handler no longer
  checks any lock, and is debounced 120ms. Typing renders local
  matches even while an AI search is in flight.

## Consequences
- Ticker/name search is now a local filter (instant after the
  one-time companies.json load). AI Search quota is burned only
  for queries the directory cannot answer.
- Behaviour preserved: fuzzy queries still reach the index;
  did-you-mean still comes from the local directory; search
  logging still fires (on AI searches and on match clicks).
- Verification: new harness `overnight-probes/search_harness.js`,
  **14/14 PASS** (local-first no-AI-call, AI fallback, empty
  state, cache, abort-supersede, debounce, suggestions during
  an AI search). `node --check` clean; no `searching`
  references remain outside one comment.
