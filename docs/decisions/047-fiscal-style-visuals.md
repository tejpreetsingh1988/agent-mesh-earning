# ADR 047 — Fiscal.ai-style visuals: vs-charts, long series, unit economics

Tej's four reference images share one idea: the
chart IS the insight — a divergence, a streak, a
per-unit gap — with total change + CAGR in the
legend and the derivation in small print. Three
buildable pieces, all deterministic (computed, not
written by an LLM, so nothing can hallucinate).

## 1. Indexed vs-chart (MO total return vs volumes)
- Total return: Nasdaq closes + dividends.
  The dividends endpoint is verified live
  (`/api/quote/{T}/dividends`: ex-date, cash
  amount, yield, annualized). Total return
  reinvests each dividend at the close on its
  ex-date — an approximation, labeled as such.
  Historical closes come from Nasdaq's
  `/historical` endpoint (verify live at build
  time; it is the same keyless family as the
  earnings calendar).
- The other series is any quarterly XBRL series
  (revenue, FCF, shares outstanding, buybacks…).
  Both series rebase to 0% at their first common
  date; the legend shows total change + CAGR per
  series, computed as (end/start)^(1/years) − 1.
- History limit: the Scout caps facts at 8
  quarters today. Chart mode fetches up to 40
  quarters for the chosen series (EDGAR holds
  full history; the payload stays small).
- V1 gap, stated plainly: MO's cigarette volumes
  are a KPI series (reported per quarter in
  releases over years), which needs KPI history
  — a later batch. V1 vs-charts demo on total
  return vs revenue / FCF / shares, which are
  XBRL and available now. MO itself passes
  admission (10-Q Oct 2026, 10-K Feb 2026) and is
  added here: 167 companies, 168 sitemap URLs.

## 2. Long quarterly bars (UBS headcount, WING AUV)
- Full-history bars for any XBRL quarterly series
  (40 quarters), same legend format (total change
  + CAGR). A deterministic read line under each
  chart, computed from the series: peak value +
  date, current vs peak %, longest rise/decline
  streak in quarters. That streak computation IS
  the honest version of "14 consecutive quarters
  down" and "Has Wingstop peaked?" — no editorial
  narrative, no cause claimed for a break. Big
  quarter-over-quarter jumps get a data-only
  marker (values + dates, never a cause).
- Headcount: annual DEI tag
  EntityNumberOfEmployees (10-K only) → annual
  bars, frequency labeled. Quarterly headcount
  (the UBS shape) needs KPI history, future.
  UBS itself is foreign (20-F) and stays out;
  headcount demos on a US name (JPM is in the
  directory). WING is in the directory; its AUV
  needs KPI history, so its v1 long chart is
  revenue/FCF, with AUV following the KPI batch.

## 3. Head-to-head unit economics (V vs MA)
- Extends the existing compare feature (Batch 8)
  with derived per-unit rows: numerator from
  verified XBRL (revenue) over a denominator.
  Each row carries its derivation footnote, the
  way Fiscal.ai prints "$44.49B over 274.8B
  transactions" under the headline number.
- V1 rows buildable now (both inputs verified):
  revenue per employee (revenue / headcount dei
  tag). Rows needing KPI denominators — revenue
  per transaction, revenue per $100 of volume,
  average transaction, revenue per store — unlock
  with the KPI batch (Batch 22), which extracts
  those denominators from releases. A row hides
  when either input is missing; nothing is
  estimated. V and MA are both in the directory,
  so the exact Fiscal.ai example is demoable once
  its denominators exist.

## Rendering
Reuse the existing Chart.js setup (makeChart +
themeColor dark-mode handling): line chart for
the vs-chart (quarter-end sampled total return
aligned to XBRL quarters), bar chart for long
series. No new charting dependency, no new vendor,
no key. The vs-chart and long charts live in the
charts rail; the unit-economics table lives in
the comparison section.

## Open at build time
Nasdaq /historical live verification; total-return
sampling (quarter-end closes); whether chart mode
reuses the briefing's Scout run or fetches series
separately (separate fetch keeps briefings fast).

## Implementation notes (Batch 26, built Nov 4, 2026)
- Nasdaq /historical VERIFIED live: with
  fromdate/todate/limit=9999 it returns 1,467 daily
  rows for MSFT (Jan 2021–Nov 2026: date, close,
  volume, open, high, low); without the date params
  it returns empty data. Closes are "$555.80"
  strings. Dividends endpoint re-verified (55 rows,
  exOrEffDate + "$0.98" amounts) — including a
  declared FUTURE ex-date, which the total-return
  builder ignores (only ex-dates inside the close
  range move the index).
- Separate fetch, as the ADR left open: the charts
  do NOT reuse the briefing's Scout run. New module
  `mesh/history.py` + `GET /history?ticker=X&metric=Y`
  on the Orchestrator Worker (same CORS-enabled app
  as /ownership). The XBRL series reuses
  async_get_quarterly_facts(limit=40) — same tag
  pick, YTD differencing, Q4 derivation, EBITDA/FCF
  as the briefing — so a chart can never disagree
  with the briefing's numbers. Frontend fetches
  after render() (fire-and-forget, memoized per
  ticker+metric); the trend switcher re-fetches for
  the new metric. Vs-chart and long bars live in
  the charts rail (CSS shows them with has-facts);
  the unit-economics block lives in the comparison
  section.
- Read line (deterministic, server-side): peak
  value + date, current vs peak %, longest
  rise/decline streaks counted in quarters, biggest
  QoQ jump (values + dates, never a cause). Legend
  numbers ride in the dataset labels (total change
  + CAGR per series).
- HEADCOUNT FINDING (changes the v1 row): the DEI
  EntityNumberOfEmployees tag is effectively
  untagged — companyfacts carries NO such row for
  MSFT, JPM, V, MA or Berkshire (their dei blocks
  hold only shares outstanding / public float).
  The revenue-per-employee row is built and wired
  (it lights up for any filer that does tag
  headcount), but it hides for all five demo names,
  exactly as the ADR's "row hides when either input
  is missing" rule requires. Nothing is estimated;
  KPI-extracted headcount (from 10-K text) is the
  future unlock, not this batch. Same for WING AUV
  and MO cigarette volumes — KPI history, later.
- Proof-sync lesson: history.py pulls async_tools'
  whole closure into the orchestrator proof
  (async_tools, edgar_facts, consensus, transcript,
  market — all stdlib-only, same set the critic
  proof already vendors). Missing it broke the
  orchestrator proof import, which cascaded into
  the scout proof test's module swap — both errors
  cleared once the closure was vendored.
- Tests: `tests/unit/test_history.py` (7 tests, fake
  fetchers); frontend harness `/tmp/b26_harness.js`
  15/15; full suite 197 passed, 1 skipped. Upload +
  live verification join the held bundle behind the
  Batch 20 verification report — live checks then:
  MO vs-chart (total return vs revenue, expect the
  +152%/-37%-shaped divergence on revenue instead
  of volumes), WING long revenue bars + read line,
  V vs MA comparison (unit row hidden — headcount
  untagged — which is itself the check).
