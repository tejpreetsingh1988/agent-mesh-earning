# ADR 086 — Batch 64: retire the yfinance quarterly-history leg

## Status
Accepted — Nov 12, 2026. Built, tested, not yet pushed (folds into
the Wave-2 push with Batch 61 + 6-K support).

## Context
Every deployed briefing's Data notes carried "get_quarterly_history
failed: No module named 'yfinance'" — the Scout's quarterly-history
leg called yfinance's quarterly_financials, and yfinance (pandas)
is not installed in the Python Workers. The price-reaction leg had
already moved to Nasdaq (Batch 28) and works live (the Nov 12
CRWV briefing carries market_reaction), so only the history leg
was broken — and it was the leg behind the trend chart and the
"metrics don't load properly" complaint.

## Decision
Retire the leg instead of replacing it, because there is no
lightweight replacement and none is needed:
- Yahoo's quoteSummary endpoint (what yfinance wraps) now
  returns HTTP 401 "Invalid Crumb" without a session crumb —
  a three-request cookie dance that is fragile from shared
  Worker egress IPs. Verified live Nov 12.
- The EDGAR overlay already returns the full 8-quarter series
  for every metric from EDGAR companyconcept (revenue,
  operating income, net income, EBITDA, EPS, shares) — the
  yfinance leg was redundant. The Scout now builds its facts
  from SEC EDGAR XBRL alone (both mirrors); the quarter-end
  fallback reads the latest fact period, which is EDGAR facts
  after the overlay, so it is unaffected.
- The async market tool `get_quarterly_history` is re-pointed
  at the same EDGAR series (async_get_filing_facts, reshaped
  into the old {period_end, total_revenue, operating_income}
  rows), so the tool contract survives and the Worker path
  never imports yfinance. The sync market.get_quarterly_history
  keeps its yfinance implementation for the Docker/local path
  only.
- The yfinance cross-check note (EDGAR vs yfinance on
  disagreement) is retired with the leg — there is nothing to
  cross-check against — and the "not yet parsed" note now says
  plainly that no EDGAR facts could be parsed.

## Consequences
- `tests/unit/test_yfinance_retirement.py` (3 tests): facts are
  EDGAR-only, no "yfinance" / "get_quarterly_history" missing
  notes, sync/async packs still match, and the reshaped async
  tool returns EDGAR rows in the old shape.
- Three fixtures updated to the EDGAR-only world
  (test_scout_analyst, test_edgar_scout_overlay, evals/runner):
  their fakes now supply get_filing_facts instead of
  get_quarterly_history; the eval's revenue check is 127.577
  (the EDGAR value) instead of 127.6.
- Full suite 342 passed, 1 skipped (incl. the 13-case eval
  suite). Proof copies synced; parity tests pass.
- Live proof owed after the push: a fresh briefing's Data
  notes must no longer mention yfinance, and the trend chart
  must carry the EDGAR series.
