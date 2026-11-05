# ADR 069 — Batch 47: Feature 16 cash-return chart

Date: 2026-11-05. Status: built + harness-tested; live check
waits on the /dividends route (Batch 44 follow-up) and the
next Pages deploy.

## Change

Frontend-only. A `#chart-cashreturn-card` section after the
dividend card (the shareholder-yield card slots in between it
and the dividend card when it lands), rendered by
`renderCashReturn(ticker)` — fetches the buybacks + shares
series (`/history`) and the dividend rows (`/dividends`) in
parallel, with the usual hide-on-failure + stale-ticker
guards. `cashReturnQuarters(buybacksSeries, sharesSeries,
dividendRows)` builds the stacked bars:
- Quarters are the buyback series' quarters (up to 12, newest
  last). A dividend belongs to the quarter whose window
  (previous buyback period_end, this period_end] its ex-date
  falls in; the earliest quarter's window opens 100 days
  before its end.
- The dividends segment uses the nearest shares-series period
  <= the quarter end; with no such period the segment is
  omitted (buybacks-only bar, flagged in the hover text).
- A quarter with neither segment is omitted from the chart
  (never drawn as zero); the footer notes how many were
  omitted.
- Fewer than 2 quarters with any data hides the card.
- Hover shows both segment values (fmtMoney, 1 decimal
  $B/$M, as the spec requires) and the quarter total.

## Deliberate deviation from the spec

The spec says the footer "carries the approximation label
from Feature 15 for the dividends segment" — but Feature 15's
label ("Dividends total uses the latest share count for all
four quarters") describes the trailing-4Q total, not this
chart: here each quarter's dividends use that quarter's own
nearest share count. Carrying the Feature 15 text verbatim
would assert something false about this chart, so the footer
states the chart's actual approximation instead: "Dividends
per quarter = per-share dividends in the quarter × the
nearest reported share count at or before the quarter end —
an approximation."

## Tests

- Harness `~/workspace/overnight-probes/cash_return_harness.js`:
  **17/17 PASS** (stacking arithmetic on the MSFT fixture —
  Q3-25 dividends use the Jul share count, Q2-26 the Apr one;
  empty quarter omitted; no-shares-period omits the dividends
  segment but keeps the buybacks bar; <2 quarters hides;
  stacked bar with 2 datasets; newest last; footer label;
  tooltip buybacks + total; fetch failure hides; stale resolve
  dropped). A first run caught a harness bug, not an app bug:
  the stub fmtMoney used 2 decimals for $B while the real one
  uses 1 — the stub now mirrors the real formatter.
- `node --check web/app.js` clean.
- Live check (MSFT chart, hover values vs the Feature 15
  trailing totals) waits on the /dividends route + Pages deploy.
