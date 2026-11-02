# ADR 012 — Streaming log on the Pages UI + parallel fetches (Nov 2, 2026)

## Context

Two user directives from Nov 2, 2026: the Pages frontend has no
streaming log (the Docker Streamlit UI had one), and briefings
are slow. The frontend hint still said "roughly a minute" while
measured full briefings ran 10–19s (GOOGL) to 42–93s (MSFT, the
slow run predating the stale-facts fix).

## Decision 1 — SSE live log

- `mesh/orchestrator_async.py` takes an optional `on_event`
  callback (sync or async) and emits one dict per step:
  `scout_started`, `scout_done`, `analyst_done`,
  `critic_attempt` (attempt number + verdict, so a Critic FAIL
  followed by re-analysis is visible, not hidden),
  `writer_done` (story model). Errors are NOT emitted here —
  they propagate, and the endpoint turns them into the
  stream's `error` event, so a failed run ends the stream
  cleanly instead of hanging it.
- `apps/orchestrator/worker_main.py` adds
  `GET /tasks/stream?ticker=X`. It runs the same pipeline
  with an asyncio.Queue between the pipeline task and the
  response generator; the generator yields `data: {...}` lines
  and a None sentinel ends the stream after the final
  `briefing` (full Briefing JSON) or `error` event. A missing
  ticker is an `error` event, not a 400, so the frontend has
  one code path for every outcome. POST `/tasks/send` is
  unchanged and stays as the fallback.
- The frontend tries the stream first. If the stream fails
  before any event arrives (stale edge cache, blocked stream),
  it falls back to POST — the briefing is identical either
  way. If the stream dies AFTER events arrived, it does NOT
  fall back: the run is already going server-side and a POST
  would start a duplicate run. The log panel shows one line
  per step with a timestamp, a "Now:" line, and a Download log
  button (plain text, one line per step). A `running` guard
  stops a second run starting while one is in flight.
- OPEN QUESTION, verified live not assumed: whether the
  Python Workers asgi adapter flushes each SSE chunk as it
  arrives or buffers the whole response. If it buffers, the
  log lines arrive all at once at the end — degraded, not
  broken — and the frontend renders them the same way, then
  the briefing. Verified live with `curl -N` (first-byte
  timing) before this is called done.

## Decision 2 — parallelize the independent fetches

- Scout (`mesh/scout_async.py`): Phase A gathers company
  facts + latest filing; Phase B gathers the six calls that
  only need the filing anchor (recent filings, filing text,
  quarterly history, filing facts, price reaction, consensus).
  The transcript call stays sequential — it needs the
  quarter label derived in step 5.
- Critic (`mesh/critic_async.py`): step 7 gathers its three
  re-queries (company facts, latest filing, consensus).
- In both, `gather(..., return_exceptions=True)` so one
  failing call cannot cancel the others, and results are
  processed in the ORIGINAL step order, so `missing[]` notes
  and `rechecked[]` entries keep their old sequence. The
  per-result handling (notes, checks, silent swallow on the
  EDGAR overlay) is unchanged from the sequential code.
- One behavioural difference, documented in code: if Scout's
  company-facts call fails, the filing call has already been
  made too — one extra read-only EDGAR request on an error
  path, never on the success path.
- NOT parallelized: the pipeline stages themselves (Scout ->
  Analyst -> Critic -> Writer) — each stage needs the previous
  stage's output. The EDGAR concept-tag fetches inside
  `async_get_quarterly_facts` were already parallelized by
  the MSFT stale-facts fix (ADR 011's follow-on work).
- NOT built: KV/Cache briefing caching. It is the obvious
  next lever for repeat tickers, but it needs a binding and
  the same env plumbing pattern as the Writer key, and it
  changes what "live" means for a briefing — a product
  decision, not a pure speedup.

## Consequences

- The frontend hint copy changes from "roughly a minute" to
  the live-log framing; measured timings are re-checked
  after deploy (HOOD end-to-end before/after) and the copy
  is corrected again if the measurements disagree.
- Tests: `tests/unit/test_streaming_speed.py` — event
  sequences (PASS and FAIL-then-PASS), concurrency proof via
  an active-call counter, output-order proof (missing[] and
  rechecked[] exact sequences), and an SSE endpoint test
  through the Orchestrator proof app with fake agent calls.
