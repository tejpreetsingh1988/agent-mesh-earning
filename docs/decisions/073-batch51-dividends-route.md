# ADR 073 — Batch 51: Feature 14 /dividends route

Date: 2026-11-05. Status: built + tested locally; push HELD
until the Batch 43 rebuild watch lands (a second push now
would trigger another Workers build and muddy the live
verification of the retry).

## Change

- `GET /dividends` in `apps/orchestrator/worker_main.py`,
  mirroring the `/history` route: calls
  `mesh/dividends.py::dividends_for_ticker(ticker)`, returns
  the payload as-is; a bad ticker is a 400, a failed fetch
  degrades to empty rows (the frontend hides the card).
- `scripts/sync-worker-proof.py`: the Orchestrator proof's
  module list gains `dividends.py` (the Batch 42 lesson — a
  `mesh/` module the Worker imports must be vendored into the
  proof, or the deploy fails at import). Proof copy verified
  byte-identical to `mesh/dividends.py`; proof `worker.py`
  differs from `worker_main.py` only by the expected Workers
  entrypoint tail.
- `tests/unit/test_dividends_route.py` (2 tests): the route
  returns the payload with the fetcher stubbed out, and 400s
  on a bad ticker with an error body.

## Tests

- Full suite: **289 passed, 1 skipped** (unchanged).
- Route + data-leg tests: **9 passed**.
- Live check (`GET /dividends?ticker=MSFT` → 4 rows + 0.7%
  yield; BROS → empty rows, card hides) waits on the push
  after the rebuild watch.
