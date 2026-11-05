# ADR 051 — Server-side stream resume (run_id checkpointing)

Date: 2026-11-04. Status: code complete; upload + live verification
held behind the Batch 20 verification report (same combined upload
as Batches 21–30).

## Problem

Batch 9's mid-stream break handling was honest about the symptom
but wrong about the mechanism: its copy said "the run may still be
completing on the server." It does not. The SSE generator's
`finally` cancels the pipeline task on disconnect, so a broken
stream kills the run. The user had to restart from Scout — the
most expensive stages — and the ~12 observed mid-stream breaks
each cost a full re-run.

## Decision

Checkpoint + event-log resume, in three parts:

1. **A new tiny TS Worker, `mesh-stream-log-proof`**
   (`cloudflare-proof/stream-log/`, same D1 database
   `agent-mesh-briefings` as search-log and transcript-log):
   - `POST /checkpoint` upserts one row per run_id
     (`stream_runs`): ticker, quarter, stage
     (started/scout/analyst/critic/done), and the stage outputs
     (pack, analysis, critique, briefing). Only fields present
     in the body overwrite stored ones (COALESCE), so stages
     accumulate and a later stage never wipes an earlier one.
   - `POST /event` appends one event (`stream_events`, primary
     key (run_id, seq)); a duplicate seq is a no-op.
   - `GET /resume?run_id=` returns the run (outputs parsed back
     to JSON) + events in seq order, or 404 for a run that never
     started.
   - Every checkpoint POST also deletes runs (and their events)
     not updated in 7 days. A resume happens minutes after a
     break; a week is generous, and the tables must not grow
     unbounded on free D1.
   - Privacy matches the other log Workers: pipeline outputs
     only, no IP/UA/fingerprint. run_id is a random uuid.

2. **The Orchestrator Worker checkpoints every stage**
   (`apps/orchestrator/worker_main.py`, copied verbatim into
   the proof by the sync script):
   - Fresh runs get a uuid run_id, a "started" checkpoint (so
     even a break during Scout leaves a resumable run — replay
     only, full pipeline), and a `run_started` first event.
   - Stage wrappers checkpoint after each agent call returns:
     Scout → pack, Analyst → analysis (every call, including
     the Critic-retry re-run — last wins), Critic → critique
     ONLY on PASS (a FAIL leaves the stage at "analyst", so a
     resume re-runs the Critic loop fresh), Writer → briefing
     with stage "done".
   - `_on_event` logs the event BEFORE queueing it, so a
     disconnect that cancels the task mid-log cannot lose an
     event the client already saw. Event logs await with a 2s
     timeout, checkpoints with 5s; failures are swallowed — a
     dead log Worker degrades resume, never the stream.
   - `GET /tasks/stream?resume_run_id=X` replays the stored
     events, then runs only the unfinished stages under the
     SAME run_id (new events continue after the highest stored
     seq, so the (run_id, seq) key never collides), so a second
     break is resumable too. A "done" checkpoint replays
     straight to its briefing with no pipeline run. An unknown
     run_id is a single `unknown_run` error event.
   - Why a new TS Worker instead of a D1 binding on the Python
     Orchestrator: the Python+D1 binding API is unproven, while
     Python→TS-Worker POST is the proven `_log_transcript`
     pattern. No new mesh modules were needed; `worker_http`
     and `orchestrator_async` were already vendored.

3. **`run_briefing_async` gains `resume_from`**
   (`mesh/orchestrator_async.py`): a stage present in
   resume_from is skipped with NO agent call and NO events,
   and its stored output feeds the next stage. A stored
   critique is honoured only on PASS. The Critic loop's
   `while...else` became an explicit `passed` flag + trailing
   `if not passed` raise — same behaviour on fresh runs
   (verified by the existing orchestrator tests), without
   re-indenting the loop body.

## Frontend (`web/app.js`)

- `run_started` sets module `lastRunId`; a fresh run clears it
  first, so a later break never resumes a stale run.
- After a break, the retry button reads "Resume run" when an id
  is held ("Run again" otherwise) and calls
  `getBriefing(ticker, quarter, null, lastRunId)`; the resume
  stream's conductor line says "Resuming run — replaying
  completed steps". Replayed events flow through the existing
  `onStreamEvent` path, so the rail rebuilds from the same
  rendering code.
- On `unknown_run`, the frontend falls back to a fresh stream
  once (the retry carries no resume id, so it cannot loop).
- Break copy corrected: "Run frozen at its last checkpoint ·
  Resume continues from there" — the old "may still be
  completing on the server" line was false and is gone.

## Honest limits

- A resume replays events, not wall-clock state: replayed
  durations are the original run's, and a stage whose DONE
  event was lost mid-log (disconnect during its 2s log POST)
  replays as not-done even though its output feeds later
  stages. The briefing still arrives; only that card's state
  looks stale.
- Event logs are best-effort; checkpoints are awaited. If the
  log Worker is down for a whole run, nothing is resumable and
  the frontend silently falls back to fresh runs.
- A resume re-runs the Critic loop with fresh attempt
  counting (a stored attempt-1 FAIL is in the event log, but
  the resumed loop gets 2 attempts again). Deliberate: the
  Critic's verdict must reflect the current analysis, not a
  stale attempt budget.
- Live verification still pending (after the held upload):
  break a real briefing mid-stream (kill the connection
  during Writer), hit Resume, and confirm the briefing
  completes without re-running Scout/Analyst/Critic; repeat
  the break during the resume itself and confirm the second
  resume still works; confirm a "done" run replays instantly.
  The stream-log Worker's Workers Builds project
  (`mesh-stream-log-proof`: build `cd cloudflare-proof/stream-log
  && npm ci`, deploy `cd cloudflare-proof/stream-log && npx
  wrangler deploy`, Access OFF) still needs creating at upload
  time, like transcript-log's did.

## Tests

- `tests/unit/test_stream_resume.py`: 8 tests (fresh baseline,
  pack-only skip, pack+analysis skip, PASS-critique skip,
  FAIL-critique re-run incl. the Analyst retry call count,
  double-FAIL raises, NOT_REPORTED_YET pack raises, stored
  pack not mutated). Full suite after Batch 31: 219 passed,
  1 skipped.
- `/tmp/b31_harness.js`: 23/23 static checks (frontend resume
  wiring, endpoint shape, checkpoint stages, seq continuation,
  done replay, log-before-queue, stream-log endpoints/prune/
  dedupe).
- Stream-log Worker verified locally (wrangler dev --local,
  local D1): checkpoint upsert + stage advance, event insert,
  duplicate seq no-op, unknown run 404, stats counts.
