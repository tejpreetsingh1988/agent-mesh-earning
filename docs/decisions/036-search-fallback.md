# ADR 036 — Search no-results local fallback

## Status
Accepted Nov 4, 2026 (Batch 18 of the product sweep).

## Context
Company search had two dead ends: an AI Search query with
zero chunks showed "No company matched", even when the
company was in the directory — and the instant suggestions
already proved the local directory could match it. The
fallback closes that gap without spending anything.

## Decision
- When an AI Search query returns zero chunks,
  `searchCompanies` runs the local directory substring filter
  (the same name-or-ticker matcher as the instant
  suggestions, top 5) and renders those matches with an
  honest note: "No indexed matches — showing directory
  matches instead." Clicking a fallback match logs and runs
  its briefing exactly like an indexed match.
- When both the index and the directory find nothing, the
  empty message says so ("in the index or the directory")
  instead of implying only the index was checked.
- The fallback result is cached with its flag
  (`{matches, fallback}` — the cache value shape changed
  from a bare array), so a repeat search replays the same
  note rather than re-querying. The in-memory cache is
  per page load, so no migration concern.
- Scope is zero-results only: the error path (AI Search
  unreachable) is untouched and still suggests the instant
  matches, as before.

## Consequences
- No new AI Search quota is burned by the fallback, and no
  new backend call exists — the directory file is already
  fetched for suggestions.
- A fallback match is only as good as the directory: a
  company outside the 149 still shows the empty message,
  which is the honest answer.
