# ADR 009 — Scout Worker v2: async fetch (pyfetch), sync path untouched

## Context

Scout Worker v1 deployed cleanly (Workers Builds, pywrangler,
workers.dev toggle) but its live GOOGL run returned
NOT_REPORTED_YET: the first EDGAR fetch died in-Worker with
"Remote end closed connection without response", reproduced
twice in ~1s. Cloudflare's docs state Python Workers do not
support synchronous requests (no worker threads, no synchronous
XHR), and every mesh fetcher uses synchronous urllib. Analyst
works in-Worker precisely because it makes zero network calls.

## Decision

- New `mesh/worker_http.py`: one async fetch layer. In a Worker
  it uses Pyodide's `pyfetch` (the documented Python-Workers
  route); anywhere else it runs the same urllib call on a
  thread via `asyncio.to_thread`, so non-Worker behaviour is
  byte-identical. Non-200 raises `WorkerHTTPError`.
- New `mesh/async_tools.py`: async mirrors of exactly the tools
  Scout calls (EDGAR, filing facts, consensus, transcript),
  reusing the sync modules' pure parsers instead of copying
  them. Market tools call the sync yfinance functions directly:
  on the Worker yfinance is absent, so the import raises and
  Scout records it in `missing`, as v1 did.
- New `mesh/scout_async.py`: `collect_evidence_async`, a
  step-for-step mirror of `collect_evidence` with awaits,
  importing the quarter rules from scout.py so they cannot
  drift. A parity test asserts both paths produce the same
  pack from the same fake data.
- `mesh/agent_app.py`: `create_app(..., async_handler=...)`
  makes /tasks/send an async endpoint; the sync endpoint is
  unchanged when only `handler` is given.
- The sync Docker path, the eval harness and the Streamlit
  path are untouched: they never import the async modules.

## Consequences

- The Worker proof now vendors worker_http, async_tools and
  scout_async (via scripts/sync-worker-proof.py); the proof
  worker's handler is async.
- Sync/async orchestration is duplicated by hand (Python has
  no sync/async-generic function). A future edit to
  scout.collect_evidence must be checked against
  scout_async.collect_evidence_async — the parity test
  catches divergence on the covered shape, not on every
  branch.
- The pyfetch path itself can only be proven by the live
  Worker deploy (pyodide is not installed locally); local
  tests prove the fallback path and the orchestration.
- A sync urllib call accidentally added to the Worker path
  will fail the same instant way v1 did — the proof test
  guards the wiring, not the transport.
