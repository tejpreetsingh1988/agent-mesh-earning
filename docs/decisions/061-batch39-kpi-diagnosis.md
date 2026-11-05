# ADR 061 — Batch 39 diagnosis: why the KPI chain returns 0

Date: 2026-11-05. Status: diagnosis complete; fix pending gateway-log read.

## The diagnostic call

Direct KPI call on BROS's pack, Writer version 81c4e73f (Batch 39),
Nov 5 ~07:36 MST: 0 items, 65.3s, `debug.errors`:

| Leg | Error | Reading |
|---|---|---|
| workers_ai | `TimeoutError` | The Workers AI call hit its 60s timeout. The KPI prompt (20,000-char release + long structured-JSON schema) does not complete in 60s; the story prompt does. Primary failure. |
| gateway ×3 | `JsException: AiGatewayError: 7003: Error` | 7003 is AI Gateway's general bad-request code (Cloudflare AI Gateway troubleshooting docs, checked Nov 5): the gateway or the provider rejected the request as invalid. The binding hides the provider's reason; the full message is in the gateway logs / via the REST API. The same routes serve the story leg, so if they 7003 for KPI they 7003 for story too — the gateway leg may have been dead since setup. |
| openrouter ×3 | `WorkerHTTPError: HTTP 429` | Direct OpenRouter calls rate-limited (free tier). The key is valid (no 401); all three models 429'ing at once suggests account-level throttling. Transient by nature; a later retry may pass. |

## What this means

The KPI leg has **no working fallback today**: Workers AI times out
on the prompt, the gateway rejects the request, OpenRouter is
throttled. The story survives on Workers AI alone because its prompt
completes in 60s. Batch 36's settle-rule fix was irrelevant because
no model ever replies — there was nothing to settle.

## Fix directions (not yet built)

1. **Workers AI timeout (primary, code):** make the KPI prompt
   completable in 60s — e.g. split KPI extraction from diagram
   generation into two shorter calls, or shrink the output (fewer
   KPIs, smaller JSON). Raising `WORKERS_AI_TIMEOUT_S` is the
   alternative, but the standing no-timeout-changes rule and the
   Orchestrator's own mode-call budget argue for a smaller prompt
   first.
2. **Gateway 7003 (config):** read the full reason in the gateway
   logs (dispatched Nov 5 ~07:40 MST, read-only). If the route or
   the stored provider key is the problem, fix it in the dashboard.
3. **OpenRouter 429 (transient):** nothing to fix in code; re-test
   later. If it persists, the free key's quota is the constraint.
