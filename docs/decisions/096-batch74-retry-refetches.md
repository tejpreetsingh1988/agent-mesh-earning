# ADR 096 — Batch 74: a failed Scout's pack is not a fast-forward

## Status
Accepted. Built and tested Nov 12, 2026. Pushed in Wave-8.

## Context
The MSFT refresh check (Batch 61a proof, Nov 12) failed twice
on the same SEC 429, and the second failure exposed a resume
bug. The first refresh died at Scout (UPSTREAM_ERROR, 0 facts)
after 12s; the saved briefing survived and "Run again" was
offered. Clicking it finished in 0.5s with the identical
failure — Scout's recorded duration was still 11.2s and both
log entries shared one second: the failed stage had been
replayed from the stored log, never re-fetched.

Root cause, in `mesh/orchestrator_async.py::run_briefing_async`:
the resume fast-forward skips any stage present in
`resume_from`, and the Orchestrator's `_scout` checkpoints its
pack regardless of status. So the checkpoint held an
UPSTREAM_ERROR pack; on resume, Scout was skipped and the very
next line raised `ValueError` on the bad status. The retry could
never succeed — the error message's "Try again in a minute"
was a dead promise. Note the asymmetry already in the same
function: a stored critique is honoured only on PASS (a stored
FAIL re-runs the Critic loop fresh). The Scout pack had no
equivalent guard.

## Decision
A stored pack fast-forwards Scout ONLY when its status is
REPORTED. A non-REPORTED stored pack is discarded — and with
it any analysis/critique derived from it, since those cannot
be valid for a run whose Scout failed — so the resumed run
fetches live. The `pack.status != "REPORTED"` raise stays, but
it now only fires when a LIVE Scout returns a bad pack (fresh
run), which is the correct behaviour. The frontend needs no
change: "Run again" still resumes the same run_id (stored
events replay, then Scout runs live), and the "Resuming run"
line stays accurate.

## Consequences
- `test_stream_resume.py` gains three tests (NOT_REPORTED_YET
  and UPSTREAM_ERROR packs re-fetch Scout live and complete;
  a bad pack discards a stored analysis too) and drops the old
  test that enshrined the raise-on-resume behaviour.
- The sync orchestrator has no `resume_from` (resume is
  stream/async-only), so no sync twin to change. Proof copies
  of `orchestrator_async.py` re-synced.
- Wave-8 files: `mesh/orchestrator_async.py`,
  `tests/unit/test_stream_resume.py`, this ADR, synced proof
  copies.
