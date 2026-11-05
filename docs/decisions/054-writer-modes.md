# ADR 054 — Writer modes: one invocation per step (Batch 34)

Date: 2026-11-05
Status: Accepted
Context: Batch 33 (ADR 053) made the Writer's three LLM chains
run concurrently under one 180s deadline, fixing the GOOGL
hung-stream break. The GOOGL resume then failed at the Writer
with HTTP 503 — the third CPU kill of the night.

## Decision

The Writer's three steps run as three separate invocations of
the Writer Worker, one per mode, and the Orchestrator assembles
the Briefing:

- The Writer payload may carry `"mode"`: `"story"`, `"kpi"` or
  `"fineprint"`. Each returns only its step result:
  `{"story_result": ...}`, `{"kpi_result": ...}`,
  `{"fine_print_result": ...}`. No mode returns the full
  briefing as before (backward compatible).
- `mesh/writer_pipeline.py` exposes the three steps
  individually (`run_story_step_async`, `run_kpi_step_async`,
  `run_fineprint_step_async`) alongside the `run_writer_steps_async`
  gather. Each step keeps its own deadline + hiding result.
- `mesh/orchestrator_async.py::run_briefing_async` takes an
  optional `writer_steps_fn(pack, analysis, trace_id) ->
  (story_result, kpi_result, fine_print_result)`; when given
  it takes precedence over `writer_fn` and the Briefing is
  assembled here with `write_briefing`.
- `apps/orchestrator/worker_main.py::_writer_steps` calls the
  Writer three times in parallel under `asyncio.gather`. The
  story call raises on failure (a briefing needs a story); the
  KPI and fine-print calls fall back to their hiding results.
  Both the POST path and the stream path use it. The stream
  path's "done" checkpoint moved out of the old `_writer` fn
  into `_run()`, on `run_briefing_async`'s return.

## Why not wall-time parallelism (ADR 053) alone

The failure was CPU, not wall time. Logs (Nov 5, 09:54:58 UTC):
POST /tasks/send, outcome `exceededCpu`, `cpuTimeMs 2010`,
`wallTimeMs 157,640`, version 4876e764 — under the 180s
deadline, so the deadline never fired. The NVDA success the
same night already burned 1,445ms CPU in 108.9s wall with KPIs
skipped and fine print empty. Local CPython profiles the
framework/serialization at ~0ms and the fine-print parse at
~0.30s (strip 0.05 + extract 0.03 + diff 0.22); the multiplier
is Pyodide itself (~3–5x on pure-Python text work). Wall-time
parallelism cannot fix a CPU budget — the fix must split the
CPU across invocations, one 2,000ms budget per step.

## Alternatives considered

- Reduce the fine-print diff CPU (cap the diff input): would
  degrade fine-print coverage for long filings and only buys
  a fraction of the budget.
- Move KPI + fine print into the Orchestrator Worker: it has
  CPU headroom (495ms over a 311s stream), but its death kills
  the whole stream with no error event — the worst place to
  add load.
- A separate "extras" Worker: same budget split, but a new
  project, dashboard, and URL for no benefit over modes on the
  existing Writer.

## Consequences

- The Writer is called three times per briefing (three
  invocations, three CPU budgets). The story leg is the
  tightest (the NVDA number suggests ~1,000–1,400ms alone in
  Pyodide); if it ever exceeds 2,000ms, the run fails and the
  Batch 31 resume machinery retries it — visible, not silent.
- `write_briefing` now runs in the Orchestrator Worker (it was
  already vendored there). `story_result` from a mode call is
  never None, so the sync `build_story` fallback never fires
  on a Worker.
- The Docker/sync path supports the same modes (sync fns);
  `mesh/orchestrator.py` (sync) is unchanged — no CPU budget
  on Docker.
- Tests: step-function tests, `run_briefing_async` with
  `writer_steps_fn` (incl. precedence over `writer_fn`), sync
  handler mode tests, proof-shape locks (mode fns present, no
  sequential awaits), orchestrator/stream fakes answer mode
  calls.
