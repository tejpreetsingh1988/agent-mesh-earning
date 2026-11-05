# ADR 055 — EDGAR fetch retry in the shared transport (Batch 35)

Date: 2026-11-05
Status: Accepted
Context: EDGAR rate-limits the Workers' shared egress IPs
(HTTP 429). Observed Nov 5, 2026: the Scout hit a 429 on
`company_tickers.json` (one stream probe failed at Scout with
it), and the fine-print step returned 0 items for NVDA despite
12 real passages waiting locally — its mode call spent 31s of
wall with 32ms CPU, i.e. the 10-Q fetch failed before any
parsing. The KPI fetch has the same exposure (it starts with
the same `company_tickers.json` call). Every EDGAR caller went
through `fetch_bytes` with no retry and, on the pyfetch path,
no per-attempt timeout.

## Decision

`mesh/worker_http.py::fetch_bytes` retries transient failures:
3 attempts, backoff delays 2s then 8s, per-attempt timeout
30s (the pyfetch await previously had none, so a hung response
could eat a whole step budget). Retryable: HTTP 429/500/502/
503/504, timeouts, and transport errors (OSError). Permanent
4xx (notably 404 — a missing document) is never retried.
`post_json` is unchanged (agent calls are not retried blindly).

## Consequences

- One change fixes the Scout, the fine-print fetch, the KPI
  fetch, consensus, history, and every other EDGAR caller.
- Worst case per call: ~3x30s + 10s delays, bounded by each
  caller's own deadline (fine-print step 180s, Orchestrator
  agent timeout 300s). The normal (success) path is unchanged
  apart from the new 30s attempt timeout.
- Tests: pyfetch 429-then-success (3 calls), 404 not retried
  (1 call), 429 always (3 calls then raise), hung pyfetch
  cut off and retried, sync-path 429 retry.
- Follow-up (not built): the same 429 exposure exists for the
  Nasdaq/Veridion fetches (ownership, history, market) — they
  share `fetch_bytes` now, so they inherit the retry too.
