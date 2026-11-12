# ADR 074 — Batch 52: Feature 15 /shareholder-yield route + card

Date: 2026-11-05. Status: built + tested locally; push HELD
with Batch 51 until the Batch 43 rebuild watch lands.

## Change

- `GET /shareholder-yield` in `apps/orchestrator/worker_main.py`,
  mirroring the `/dividends` route: calls
  `mesh/shareholder_yield.py::shareholder_yield_for_ticker(ticker)`,
  returns the payload as-is (null when any input is missing —
  the frontend hides the card); only a bad ticker is a 400.
- `scripts/sync-worker-proof.py`: the Orchestrator proof's
  module list gains `shareholder_yield.py` (same Batch 42
  lesson as dividends.py). Proof copy verified byte-identical
  to `mesh/shareholder_yield.py`.
- Frontend card `#chart-yield-card` in `web/index.html`,
  directly after the dividend card (so the rail reads
  dividend → yield → cash-return, as specced), rendered by
  `renderShareholderYield(ticker)` in `web/app.js` following
  the renderDividends pattern (hide first, fetch, stale-ticker
  guard, show on success/hide on failure). The card shows the
  ratio ("Shareholder yield: 1.3%") plus all three inputs
  (buybacks, dividends, market cap) so the ratio can be
  rechecked by hand, and the payload's approximation note.
  Called from the briefing render alongside renderDividends.
- `tests/unit/test_shareholder_yield_route.py` (3 tests):
  payload returned, null on missing input (BROS), 400 on a
  bad ticker.

## Tests

- Harness `~/workspace/overnight-probes/shareholder_yield_harness.js`:
  **7/7 PASS** (MSFT 1.3% + all three inputs + approximation
  note; null payload hides; fetch failure hides; stale
  resolve dropped). One harness bug found (the BROS test left
  lastBriefing as MSFT, so the stale guard fired first) —
  harness-side, not app code.
- Route + data-leg tests: **12 passed**.
- `node --check web/app.js` clean.
- Live check (`GET /shareholder-yield?ticker=MSFT` → 1.3%;
  BROS → null, card hides) waits on the push after the
  rebuild watch.
