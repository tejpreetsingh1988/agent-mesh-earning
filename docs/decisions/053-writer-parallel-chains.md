# ADR 053 — Writer steps run concurrently under a per-chain deadline (Batch 33)

## Status

Accepted Nov 5, 2026. Fixes the GOOGL stream break diagnosed the same night.

## Context

The Writer ran its three LLM steps SEQUENTIALLY in the async
proof handler: story, then KPI extraction, then fine print.
Each step runs the same fallback chain — Workers AI (60s
timeout), then 3 gateway models (60s each), then 3 direct
OpenRouter models (60s each) — up to 420s worst case per step,
1,260s for the three.

For GOOGL's Q3 2026 briefing the Writer was still running at
299s. The Orchestrator's stream request was then canceled by
the Cloudflare runtime as "hung" at ~311s wall with the
verbatim error "The Workers runtime canceled this request
because it detected that your Worker's code had hung and would
never generate a response." The client saw the stream simply
end: no error event, no briefing. The Writer itself was never
CPU-killed (946ms CPU on that invocation); it was just too
slow. The Orchestrator's own 300s agent timeout never fired
either — the runtime's hang detection fired first.

The NVDA April briefing the same night took 110s in the Writer
because KPIs were skipped (no exhibit 99.1) and fine print
returned empty. GOOGL has a 99.1 file and a real fine-print
diff, so all three chains ran — the sequential sum is what
killed it.

## Decision

- New module `mesh/writer_pipeline.py::run_writer_steps_async`
  runs the three steps concurrently under `asyncio.gather`,
  each wrapped in a 180s deadline (`WRITER_CHAIN_TIMEOUT_S`).
  Worst-case Writer wall time is now ONE deadline, not the sum
  of three chains; a full stream run stays ~15s pipeline +
  ≤180s Writer, well under the ~300s edge limit.
- A chain that times out or raises falls back to its designed
  hiding result: deterministic story for the story chain, empty
  KPIs / empty fine print for the others. A chain failure can
  never break a verified briefing.
- The three steps are independent, so concurrency changes no
  semantics: KPIs are not in the story prompt and fine print is
  its own section.
- The Docker/sync path (`agents/writer/main.py`) stays
  sequential — it is not the live path and its blocking calls
  cannot await. The proof transform in
  `scripts/sync-worker-proof.py::_writer()` now emits a single
  `run_writer_steps_async` call; the proof vendors
  `writer_pipeline.py`.
- `tests/unit/test_writer_pipeline.py` (3 tests): the steps
  overlap (three 0.3s steps finish in <0.6s), a slow chain
  hits the deadline and falls back, a raising chain is
  contained. `test_worker_proof_full_app.py` locks the proof
  shape: `run_writer_steps_async` present, no sequential
  `await build_story_async / kpis_for_pack_async /
  fineprint_for_pack_async`.

## Consequences

- Concurrent chains triple the burst load on the LLM transports
  (Workers AI + gateway + OpenRouter see 3 requests at once).
  OpenRouter free tier allows 20 req/min; a worst-case burst
  is 3 chains x 5 attempts = 15 requests, under the limit.
  Workers AI and gateway limits were not a problem in practice.
- KPI and fine-print EDGAR fetches now run concurrently too;
  a 429 on either is already handled as best-effort empty.
- A story that legitimately needs >180s now falls back to the
  deterministic story instead of hanging the briefing. The
  180s figure is a judgment call: NVDA's story took ~110s
  end-to-end inside the Writer, so 180s keeps real stories
  while bounding the stream.
- The GOOGL run that broke (run_id
  a8f58d68-0756-43d1-ad7b-a80d2ed24e3d) is checkpointed at the
  Critic stage in the stream log; resuming it after this deploy
  is the live proof of both this fix and Batch 31's resume.
