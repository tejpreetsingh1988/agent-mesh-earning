# ADR 083 — Batch 62: exhibit 99.1 resolution for descriptively named press releases

## Status
Accepted — Nov 12, 2026. Built, tested, not yet pushed (folds into the
follow-up push with Batches 60/63 + CoreWeave).

## Context
The CoreWeave test briefing (run 70ed0e4a, Nov 12) proved the core
pipeline handles a new 10-Q filer — Scout 75 facts, Analyst 18
claims, Critic PASS on attempt 1, Writer story 2,047 chars — but the
KPI, fine-print and diagram legs all came back empty
(`kpi_debug: fetched_chars 0, settled_on "no_text"`). The cause was
not a model or rate-limit failure: CoreWeave's Nov 10 results 8-K
carries its press release as `coreweave3q26earningspress.htm`, and
`exhibit_991_candidates` only matched the ex99.1 filename shape, so
the walk found nothing and the legs got no input text.

## Decision
Extend `exhibit_991_candidates` (mesh/edgar.py) with a second pass:
filenames matching a press-release shape (`press` or
`earnings-release`) are returned after the ex99.1-shaped names.
Callers (kpi.py, past_reactions.py) already try each candidate in
order until one yields text, so no caller changes. The 8-K's own
text ("attached hereto as Exhibit 99.1") is what makes a
descriptive name the exhibit; the matcher trusts the name shape,
not the exhibit table. A results 8-K whose release is named
neither way would still be missed — parsing the 8-K exhibit index
is the follow-up if that ever shows up.

## Consequences
- One new unit test (descriptive name tried after ex99.1 names);
  existing test unchanged. `tests/unit/test_kpis.py`: 32 passed.
- Proof copies synced via scripts/sync-worker-proof.py; all four
  existing copies (scout, critic, writer, orchestrator) are
  byte-identical to mesh/edgar.py. (There is no analyst proof copy
  of edgar.py — the Analyst does not vendor it.)
- Live proof requires the push: the deployed Workers still carry
  the old matcher, so a CRWV re-run only proves KPIs after this
  batch deploys. That re-run is owed after the push.
