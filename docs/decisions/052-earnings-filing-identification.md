# ADR 052 — Earnings 8-K identification (Item 2.02) + derived-Q4 fiscal pairing

Date: Nov 5, 2026 (00:05–00:20 MST). Status: coded, tested, proven on
real EDGAR data; ships with the combined upload (Batches 21–31).

## Context

The Batch 20 re-verification (Nov 4, 2026, ~23:50 MST) proved the
fiscal picker itself works — the April NVDA briefing ran with the
correct quarter, facts ≤ 2026-04-26, Critic PASS — but surfaced
two correctness bugs in the shared evidence path that the picker
exposed rather than caused. Both are fixed here, not in Batch 20.

## Bug 1 — the latest "earnings filing" was often not earnings

`get_latest_earnings_filing` picked the most recent 8-K of ANY
kind. Frequent filers file 8-Ks for meetings, debt, and other
items between quarters, so the pick was routinely wrong:

- NVDA latest (July quarter): report_date **2026-09-03** — a
  non-earnings 8-K. The real earnings 8-K was Aug 26, 2026.
  Consensus was therefore unavailable even though Nasdaq's Aug 26
  calendar row has NVDA ($2.22 vs $2.09 forecast, +6.22%).
- NVDA April quarter: the requested-quarter pick fell back to a
  **June 30, 2026** non-earnings 8-K (see Bug 2 for why the real
  one was not even a candidate). Consensus + price reaction
  anchored to the wrong date.

The fix (sync `mesh/edgar.py`, async `mesh/async_tools.py` —
the cloud path uses the async mirror): walk recent 8-Ks newest
first (max 6), fetch each primary document's head (first 12k
chars via the existing `get_filing_text`), and pick the first
whose head contains **Item 2.02** (Results of Operations and
Financial Condition) — the item under which earnings releases
are furnished. Fall back to the most recent 8-K when none
matches; never fail a briefing over identification.

The signal is the Item 2.02 heading, NOT an exhibit name:
NVDA inlines the release in the 8-K body — no separate exhibit
99.1 exists in its 8-K indexes (verified live Nov 4, 2026 for
the May 20, Aug 26, and Sep 3 8-Ks). An exhibit-99.1 check
alone would miss NVDA entirely. (Consequence for Batch 22: its
KPI fetch, which looks for exhibit 99.1 files, also needs a
primary-document fallback for such companies — follow-up, not
this ADR.)

## Bug 2 — requested-quarter candidates aged out of the window

The requested-quarter path called `list_recent_filings` with
limit 50. The submissions "recent" array holds 1000 rows and
the limit is a client-side slice, so 50 costs nothing — but it
ages out the earnings 8-K for frequent filers. NVDA's May 20,
2026 earnings 8-K (the real Q1 FY2027 report date — Nasdaq's
May 20 calendar row has NVDA, eps $2.39, fiscalQuarterEnding
Apr/2026; there is no NVDA row on May 27 or May 28) was outside
the 50-window by November. The consensus probe therefore never
saw it and `_pick_quarter_filing` fell back to the earliest
in-window 8-K.

The fix (sync `mesh/scout.py`, async `mesh/scout_async.py`):
requested-quarter limit 50 → **300**; Phase B latest-path
limit 10 → **50** (the picked earnings filing can be ~10 weeks
old; the 10 most recent filings span only ~3–4 weeks for
frequent filers, so the reportDate match would miss it).

## Bug 3 — derived Q4 paired the wrong fiscal years

`derive_q4_rows` keyed the FY and 9-month YTD rows by the
calendar year of their end date. For fiscal calendars that
pairs the wrong rows: NVDA's FY2025 10-K ends Jan 2025 while
FY2026's 9-month YTD ends Oct 2025 — same calendar year,
different fiscal years — and FY − YTD came out as **−$17.3B**
of "revenue", a negative fact that shipped in live packs, while
the real Q4 FY2026 row (Jan 2026) never appeared. The same gap
also made the April briefing's QoQ claims stale (Jul→Oct 2025,
the latest pairable QoQ once Jan 2026 was missing) and kept
"Jan 2026" out of the quarter picker.

The fix (`mesh/edgar_facts.py`, shared by both paths): key by
the row's `fy` field, falling back to end-date year for rows
that lack one, with an `fp` guard (YTD must be Q3, FY must be
FY). Proven on live EDGAR data Nov 5, 2026 (NVDA CIK 1045810):
2026-01-25 **$68.127B** derived (FY $215.938B − 9M $147.811B)
and 2025-01-26 **$39.331B** derived (FY $130.497B − 9M
$91.166B) — both positive, both matching NVDA's actual Q4
revenues ($68.1B / $39.3B).

## Honest limits

- NVDA's April consensus, once the right filing is picked, is
  reported EPS $2.39 with **no Nasdaq forecast** (epsForecast
  empty, noOfEsts N/A) — beat/miss is genuinely unavailable
  from free sources for that quarter, not a code failure. The
  parser returns status "available" with eps_estimate None;
  the Analyst emits no beat/miss claim and the badge hides.
- The consensus probe still only checks the 5 earliest
  candidates in the window; if more than 5 non-earnings 8-Ks
  precede the earnings one, the probe misses it and the pick
  falls back unconfirmed. Raising the window to 300 makes this
  rare; widening the probe is a follow-up, not this ADR.
- The Item 2.02 walk fetches up to 6 document heads per
  latest-quarter run (usually 1–2). The Scout is ~8s today;
  this adds ~1–3s in the worst case.

## Verification

- 9 new tests, all passing: `test_derived_q4_fiscal.py` (4:
  NVDA pairing, calendar-company regression, no-fy fallback,
  non-Q3 guard), `test_latest_earnings_filing.py` (3: sync pick,
  sync fallback, async pick), `test_quarter_selector.py` +2
  (window test, sync + async — earnings 8-K at index 100 is
  found with the 300-row window).
- Full suite after the fixes: **232 passed, 1 skipped** (was
  223 passed, 1 skipped). One test-authoring catch: the
  first version of the filing test cleared the `edgar._tickers`
  lru_cache, which left fake NVDA-only tickers cached for
  later tests in the same process and broke GOOGL lookups —
  fixed by patching `_tickers` itself instead of `_get_json`
  + cache_clear.
- Proof sync re-run; scout/orchestrator/writer proofs contain
  `_is_earnings_8k_text` and the 300 limit (grep-verified).
- Live proof (post-upload): NVDA April briefing → report_date
  2026-05-20, consensus present (reported $2.39, no forecast),
  QoQ claims Apr 2026 vs Jan 2026, picker offers Jan 2026;
  NVDA latest → report_date 2026-08-26, consensus $2.22 vs
  $2.09 (beat), market reaction anchored to Aug 26.
