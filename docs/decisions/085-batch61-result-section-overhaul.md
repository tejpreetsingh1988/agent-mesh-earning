# ADR 085 — Batch 61: result-section overhaul (reliability + numbers + presentation)

## Status
Accepted — Nov 12, 2026. Built, tested, not yet pushed (folds into
the Wave-2 push with Batch 64 + 6-K support).

## Context
The live MSFT check (browser task, Nov 12, 09:34–09:40 PST) found
the result section is not just messy — it is unreliable. A fresh
MSFT run failed on an SEC rate limit, and the app told the user
MSFT had not reported yet; the failed refresh had already deleted
the saved MSFT briefing from that browser's localStorage, leaving
a blank page with no retry. The completed DUOL briefing showed
the number defects end to end: "$0.3B -> $0.3B" for +13.7% growth,
"$0.0B -> $0.0B" for -31.2%, "REVENUE 0.3 USD_B", a $5.95 EPS
outlier driving a -90.9% YoY takeaway with no context, a
change_pct shown as an ownership share ("2,332,543 shares
(2019.569%)"), 103.67% institutional ownership unflagged,
chart labels run together ("Revenuegrowth") and diagonal, and
claims-table rows turning white-on-white in dark mode.

## Decision

### 61a — reliability
- **UPSTREAM_ERROR status.** A SEC 429 / transient transport
  failure is now its own EvidencePack status, in both Scout
  mirrors, instead of NOT_REPORTED_YET. The orchestrators raise
  with the pack's own status, and `error_event` carries it as
  `status` so the frontend can tell a retryable rate limit from
  a genuine not-reported verdict. The Critic gate is
  status-based (`!= "REPORTED"`) and already covers it.
- **A refresh never deletes first.** The Refresh button used to
  clear every cached key for the ticker before running live.
  Now it forces a live run (new `force` param on getBriefing)
  and the stale keys are cleared only by a SUCCESSFUL save
  (saveBriefingCache, same try block as the write — a failed
  save keeps the old copy).
- **A failed run restores the saved copy.** showBriefingError
  renders the cached briefing under the error with its banner
  when one exists, so a failed refresh leaves a usable page.
- **Retry for upstream errors.** The error box offers "Run
  again" when the status is UPSTREAM_ERROR (or the message
  carries it, for the POST fallback); the retry is a live
  re-run, never a cache serve.

### 61b — numbers
- **Analyst `_fmt`:** USD_B values below $1B render in
  millions ("$300M", "$40M") instead of "$0.3B" / "$0.0B".
- **Base-effect note:** when a YoY/QoQ move of >=25% is driven
  by a base quarter >2.5x the series median while the current
  quarter is normal, the claim says so ("base quarter was 8.3x
  the series median ($0.72); the move is mostly a base effect,
  not a run-rate change"). DUOL's -90.9% EPS YoY gets the note;
  normal series get none. Verified against EDGAR: DUOL's $5.95
  is a real XBRL value (the attributable series), so the fix is
  annotation, not a data correction.
- **Glance:** money renders through fmtMoney, never a raw unit.
- **Filings:** the " — " separator before "Open filing" is now
  " · " (it read as a dangling dash).
- **Funds:** change_pct is labelled as the change it is
  ("+2019.6% change in shares"), and institutional ownership
  above 100% carries a note (Nasdaq counts lent shares twice).

### 61c — presentation
- **Growth chart labels:** the "YoY" strip ate the spaces
  around it ("Revenuegrowth"). Labels are now the bare metric
  ("Revenue", "Operating income", "GAAP EPS") with
  `maxRotation: 0`.
- **Dark-mode Analyst table:** the hover/selected/header/detail
  colours were hardcoded light (#fff / #f8fafc / #3f3f46) —
  white-on-white in dark mode. All five now use theme tokens.
- **Baton rail:** on a stream or POST error, every leg that is
  not already Done is marked Failed (the Nov 12 run left the
  rail contradicting the ledger).
- **Not a defect:** the "truncated" takeaway text was the
  browser task's own excerpting — the Analyst's consensus claim
  text is complete in the source. No renderer change.

## Consequences
- Python: `tests/unit/test_upstream_error.py` (6 tests) +
  `tests/unit/test_analyst_fmt_base_effect.py` (5 tests);
  full suite 338 passed, 1 skipped.
- Frontend: new `overnight-probes/batch61_harness.js`,
  **13/13 PASS** (funds labels, growth labels, glance,
  save-cleanup incl. the failed-save case). All 17 existing
  app.js-slicing harnesses re-run green (226 checks).
- Proof copies synced; parity tests pass.
- Live proof owed after the push: a forced MSFT refresh
  against a 429 (or a simulated upstream failure) must keep
  the saved briefing and offer retry; a fresh DUOL briefing
  must show $300M-style claims, the EPS base-effect note, and
  the corrected funds rows.
