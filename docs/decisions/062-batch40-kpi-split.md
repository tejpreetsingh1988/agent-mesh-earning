# ADR 062 — Batch 40: split KPI extraction from diagram generation

Date: 2026-11-05. Status: built + tested, upload pending.

## Diagnosis (ADR 061, corrected by the gateway logs)

The Batch 39 diagnostic call named all seven leg failures:

- `workers_ai: TimeoutError` — the Workers AI call hit its 60s
  timeout. The combined prompt (20,000-char release + a long
  structured-JSON schema asking for KPIs AND a diagram) does not
  complete in 60s; the story prompt does. **The only code-side
  failure, and the one this batch fixes.**
- `gateway ×3: AiGatewayError: 7003` — the gateway logs show the
  same requests as HTTP 429 / `rate_limited`. The binding's 7003
  is how it surfaces the provider's 429; the logs hold no fuller
  reason. The routes WORK — nemotron and cohere both succeeded at
  12:02 UTC Nov 5 (5,328 input / 1,800 output tokens). Since
  ~12:45 UTC every call 429s: OpenRouter rate-limiting the stored
  key (free tier). Nothing to fix in code; it eases with time.
  `story-gemma` never succeeded in 24h — its model mapping may
  be wrong/retired (secondary, not addressed here).
- `openrouter ×3: HTTP 429` — same rate limit, same key.

## Change

Split the one combined call into two smaller calls:

- `kpi_prompt` — KPIs only (the diagram instructions removed).
  Same 20,000-char window: the KPI highlights sit throughout a
  release (BROS's shop counts are at char ~14,000), and the input
  prefill is not the bottleneck — the output is.
- `diagram_prompt(kpis, release_text)` — diagram only, with the
  extracted KPI names and a 6,000-char window (company
  description/highlights sit early). Small input, small output.
- Shared `_extract_json_obj` (fence strip + trailing-comma repair,
  factored out of `parse_kpi_response`); new
  `parse_diagram_response`; `_settle_kpis_reply` replaces
  `_settle_reply` (phase-1 settle on KPIs only, Batch 36 rule
  intact).
- `extract_kpis_async` / `extract_kpis_sync`: phase 1 extracts
  KPIs down the chain (Workers AI → gateway → OpenRouter); phase 2
  draws the diagram from the extracted KPIs, on the legs from the
  phase-1 winner onward, best-effort — a failed diagram never
  loses the KPIs, and it runs even on an empty KPI settle (a
  release can have a clear business model and no operating KPIs).
- Debug gains `debug["diagram"]` (`"ok"` / `"none"`); the
  phase-2 failures are recorded as `diagram:<leg>` errors.
  `replies` still counts phase-1 returns only.

## Tests

- 3 new split tests: diagram drawn in a second call on the same
  model (async + sync); diagram failure keeps the KPIs.
- 5 updated tests: call patterns now include the phase-2 calls;
  the prompt test asserts the diagram lives in `diagram_prompt`.
- Full suite: **269 passed, 1 skipped** (was 266).

Lesson recorded: a slice replacement of `extract_kpis_async`
deleted `_call_openrouter_async` (it sat between the two extract
functions); the import error surfaced only in the full suite.
Restored verbatim from the proof copy. Verify imports after any
slice edit.
