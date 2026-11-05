# ADR 059 — Batch 38: KPI chain debug telemetry

Date: 2026-11-05. Status: built + tested, upload pending.

## The question Batch 36 left open

Batch 36 deployed live (Writer version 10707c67, build 4e81de2f) and the
direct KPI call on BROS's pack was re-run against it: still **0 items, no
diagram, no source_url, 63.8s** — identical to the pre-Batch-36 call
(64.6s). Batch 36 changed the settle rule, so a 0 after it means either
two models returned clean-empty, or the chain ran out of models after a
Workers AI timeout. From the outside these are indistinguishable.

Two hypotheses were ruled out by local checks before building this batch:

1. **Window starvation — ruled out.** The BROS 99.1's first 20,000 chars
   (the prompt window) contain the KPIs: "5.4% Company-Operated and
   4.4% Systemwide Same Shop Sales Growth" at char ~181, "shop count"
   at 14,147, "AUV" at 14,517. The model sees the KPIs.
2. **Deadline kill — ruled out.** `WRITER_CHAIN_TIMEOUT_S` is 180s;
   the 64s call genuinely settled, it was not cut off.

The fine-print leg still succeeds on the same 99.1 via the same
`fetch_release_text_async`, so the fetch is not the differentiator
either. The remaining unknown is what the models actually return for
the KPI prompt — and the Worker gave no way to see it.

## Change

A `debug` dict rides the KPI chain, filled in place, returned in the
`kpi_result` of the direct mode call:

- `kpis_for_pack_async/sync`: `fetched_chars`, `fetched_url`, and
  `settled_on = "no_text"` when the fetch yields nothing, `"error"`
  on an unexpected exception.
- `extract_kpis_async/sync`: `replies` (successful model returns),
  `settled_on` (`items` / `diagram` / `empty` / `exhausted` /
  `no_key`), `last_parse_ok` (did the last reply parse as JSON?),
  `last_reply_head` (first 200 chars of the last reply).
- `run_kpi_step_async` passes the dict through and includes it as
  `"debug"`; a step that never completes normally gets
  `settled_on = "incomplete"`.

Safety: `write_briefing` reads only `items` / `source_url` /
`diagram` from `kpi_result`, so the debug key never reaches a
Briefing — it is visible only on the direct mode call. The debug
values are ints/strings/bools (JSON-safe); `last_reply_head` is
model output derived from public SEC text, no secrets, no user data.

## Tests

- 3 new tests in `tests/unit/test_kpis.py`: debug records a
  two-model empty settle, a first-model items settle, and a failed
  fetch (`no_text`).
- `tests/unit/test_writer_pipeline.py`: fakes updated for the new
  `debug` kwarg; the exact-dict assertion now includes the debug key.
- Full suite: **265 passed, 1 skipped** (was 262).

## Next

Re-run the direct KPI call on BROS's pack against the deployed Batch 38
Writer and read `kpi_result.debug` — it names the failure (fetch /
models / settle) instead of guessing it.
