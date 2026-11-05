# ADR 068 — Batch 46: Feature 15 shareholder yield, data leg

Date: 2026-11-05. Status: data leg built + tested + live-probed;
route (`GET /shareholder-yield`) and frontend card land in the
follow-up batch, after Batch 43 pushes (the route edit touches
the Orchestrator's worker_main, Batch 43's file — same gate as
Feature 14's route).

## Source verification (live probe, 2026-11-05)

The history route already serves both series the formula
needs, in raw units — probing first corrected the spec's
`shares_B x 1e9` reading: the `buybacks` series is unit **USD**
(raw dollars; MSFT last 4 quarters 7.415 + 4.627 + 4.579 +
4.379 = $21.0B) and `shares_outstanding` is unit **shares**
(raw counts; MSFT latest 7,426,194,552 on 2026-10-22). No
billion conversions are applied anywhere in this module.

## Change

New `mesh/shareholder_yield.py` (pure formula + async
assembler over existing paths only):
- `trailing_sum(series, n=4)` — last 4 values; None when fewer
  than 4 exist (the trailing window is exactly 4 quarters).
- `latest_value(series)` — most recent value, or None.
- `shareholder_yield(b, d, mc)` — (b+d)/mc*100, 1 decimal;
  None on any missing input or non-positive market cap.
- `shareholder_yield_for_ticker(ticker, ...)` — gathers the
  buybacks + shares series (`history_for_ticker`) and the
  dividend payload (`dividends_for_ticker`) in parallel;
  requires the buybacks unit to be USD and the shares unit to
  be shares (a unit change hides the card instead of computing
  on unknown units); dividends total = sum of the last 4
  per-share dividends x latest shares; market cap = last close
  x latest shares; the payload carries the approximation note
  ("Dividends total uses the latest share count for all four
  quarters — an approximation.").

## Live proof (assembler run against the real endpoints)

- MSFT: buybacks $21.0B, dividends $27.03B, market cap
  $3.668T, shareholder yield **1.3%** (hand-checked:
  48.03/3668.17 = 1.31%).
- BROS: None — no dividends, so the card hides, as specified.

## Tests

- 7 new unit tests (formula on the real MSFT fixture inputs;
  trailing window exactly 4; yield hides on missing input;
  fake-fetch assembler = 1.3% with the approximation label;
  hides when dividends are short; hides on wrong unit; bad
  ticker raises).
- Full suite: **289 passed, 1 skipped** (was 282).
