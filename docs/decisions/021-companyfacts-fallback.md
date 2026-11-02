# ADR 021 — Companyfacts fallback for empty/stale companyconcept picks

## Status
Accepted Nov 2, 2026, after the Visa investigation (subagent,
read-only, same day).

## Problem
The Worker Scout fetches XBRL facts exclusively from EDGAR's
per-tag companyconcept endpoint. For Visa (CIK 1403161), that
endpoint returns EMPTY units (valid JSON, HTTP 200) for the
current revenue tag — and for operating income — while the
companyfacts endpoint holds full current data for the same
tags. The picker then falls back to the only tag with rows,
the retired `Revenues` tag (last 10-Q 2019-06-30), and the
Critic's staleness gate correctly FAILs the briefing. The
picking logic was not buggy and the tag was not missing from
`ALTERNATE_TAGS`; the fetch layer returned empty for the
winning tag, with no alternate source.

## Decision
Add a companyfacts fallback to `mesh/edgar_facts.py`
(`get_quarterly_facts`) and its Worker mirror in
`mesh/async_tools.py` (`async_get_quarterly_facts`):

- Trigger: a metric's companyconcept pick is empty, or its
  newest row is more than `STALE_PICK_DAYS` (400) before the
  earnings report date (`needs_companyfacts_fallback`). 400
  days is deliberately generous: a normal pick sits within
  ~120 days of the filing, so the fallback fires only for
  genuinely broken picks.
- Mechanism: fetch the ticker's companyfacts payload ONCE
  per Scout run (lazy cache, fetched only when some metric
  needs it), re-read the SAME `ALTERNATE_TAGS` from it via
  synthetic `{"units": units}` payloads through the shared
  `_rows_from_payload` parser, and re-run `pick_latest_tag`.
  Only the alternate tags are read — never all ~600 tags.
- Keying: the fallback keys on empty units / stale picks,
  NOT on HTTP errors, because the failure mode is a 200 with
  empty data. If the companyfacts fetch itself fails, the
  Scout keeps today's behavior (stale pick + Critic gate),
  never a crash.
- Opt-in: `companyfacts_fetch` defaults to unset (no
  fallback), which keeps existing tests hermetic. The two
  live call sites pass it explicitly — `get_filing_facts`
  (sync, via `direct_client`) and `async_get_filing_facts`
  (Worker) — and both Scouts thread the filing date as
  `report_date` so the staleness check can run. Callers
  that pass no report date get the empty-pick trigger only.

## Why MSFT and other working tickers are unaffected
The fallback fires only when companyconcept is empty or the
pick is stale. Tickers whose current tag returns rows via
companyconcept (MSFT's does) never touch companyfacts, and
`pick_latest_tag` semantics are untouched — the MSFT
retired-tag fix keeps working byte-for-byte.

## What the fix recovers for Visa — and what it does not
Visa's current tag in companyfacts has 40 quarterly 10-Q
rows through 2026-03-31 ($11.23B). Visa's July 2026 10-Q
contributes ZERO rows to companyfacts, so June 2026 is
currently unobtainable from EDGAR XBRL at all; 2026-03-31
is the latest obtainable quarter. That is inside the
Critic's 365-day window of quarter_end 2026-09-30, so the
briefing PASSES (with the Scout's existing "latest
available period" notes). Side gap, not blocking: no
diluted-EPS tag for Visa was found in companyfacts — that
needs its own tag hunt later.

## Verification
`tests/unit/test_companyfacts_fallback.py` (8 tests):
Visa-shaped fixtures (stale Revenues + empty current-tag
companyconcept; current tag through 2026-03-31 in
companyfacts) assert the fallback picks the current tag,
the companyfacts fetch happens at most once per run, a
fresh pick never triggers it, a stale pick without a report
date keeps the old pick, and an empty pick triggers it
without a date. `tests/unit/test_stale_facts_fix.py` passes
unchanged.
