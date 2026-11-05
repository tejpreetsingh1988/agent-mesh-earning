# ADR 064 — Batch 42: serialize the Writer steps; surface the KPI debug

Date: 2026-11-05. Status: built + tested, upload pending.

## What the logs proved

The Batch 41 window fix works in isolation (direct KPI call:
12 items + diagram, first model, live) but the KPI and
fine-print legs return empty in full runs. The Writer logs for
2026-11-05 15:36–15:41 UTC show the third failure mode, after
the Workers AI timeout (ADR 061) and the OpenRouter rate limit
(ADR 061): **the Python Worker hits the 2,000ms CPU limit in
clusters** — "Worker exceeded CPU time limit", HTTP 503, plus
cascade resets ("Python Worker was reset because another
request exceeded the CPU time limit") of sibling requests,
at the same minutes the three parallel mode calls fire.

The parallel mode calls (Batch 34) each spin up a Python
isolate; three at once pay cold-start/import CPU simultaneously,
and they also contend for the Workers AI free tier (one
account) and for SEC (the 99.1 fetched twice concurrently).
One full run errored after Critic PASS with "HTTP 500 for
mesh-writer-proof/tasks/send" — the edge returning 500 for a
reset isolate, most likely; no 500 appears in the Worker logs
themselves.

An open discrepancy, recorded honestly: the logs show NO
Writer events at all for two of the full runs' windows
(15:44, 15:47 UTC) even though those runs produced stream
events. The times I derived for those runs may be off, or the
dashboard filtered them. Nothing is built on that gap.

## The bigger find: the Orchestrator proof's schema was stale

While verifying the upload, a diff of every proof file
against GitHub main showed the Orchestrator proof's
`mesh/schemas.py` was missing `transcript_excerpt`,
`quarter_end`, `fine_print`, `kpis`, `kpi_source_url` and
`diagram` — fields added by Batches 22/30/41 that were
uploaded to the Writer proof and to `mesh/` but never
re-uploaded into the Orchestrator proof. Pydantic drops
unknown constructor kwargs silently, so `write_briefing`
computed the KPIs and fine print and the Briefing model
threw them away: the full-run briefing for BROS (run
5e709f27) contains NO `kpis`, `fine_print`, `diagram`,
`kpi_source_url` or `quarter_end` keys at all. That alone
explains why the KPI and fine-print sections never appeared
in a full-run briefing, regardless of what the KPI mode call
returned. This batch restores those fields in the
Orchestrator proof. Lesson: after ANY `mesh/` change, diff
every proof copy that vendors it against GitHub main before
uploading — the sync script regenerates the copies, but the
upload list is what actually ships them.

## Change

1. `_writer_steps` (Orchestrator) runs the three mode calls
   SEQUENTIALLY — story, then KPI, then fine print — one await
   after the other. Sequential calls warm one isolate and reuse
   it, and the steps no longer contend for the model, for SEC,
   or for the CPU budget at the same instant. Cost: wall-clock
   is the sum (~40s story + ~64s KPI + ~21s fine print ≈ 125s,
   inside the 300s agent timeout and the ~300s stream limit).
2. The Briefing gains a `kpi_debug` dict (populated by
   `write_briefing` from the KPI result's debug), so a full
   run's KPI outcome — settled_on, replies, errors, diagram —
   is diagnosable from the stream's briefing event alone, with
   no dashboard log read. Not rendered by the frontend.

## Tests

- New: `_writer_steps` calls the modes in order
  story → kpi → fineprint (mocked `_agent_call`, order recorded).
- New: `write_briefing` carries `kpi_debug` from the KPI result.
- Full suite: **272 passed, 1 skipped** (was 270).
