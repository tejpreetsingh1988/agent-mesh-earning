# ADR 065 — Batch 43: retry the KPI mode call once on exhaustion

Date: 2026-11-05. Status: built + tested, upload pending.

## What the Batch 42 full run proved

Run f8553e9a (BROS, Nov 5 ~09:57 MST, Writer 49ba2b09,
Orchestrator 625914ef) completed in 3m 2.7s with a briefing
that now CARRIES the KPI fields and `kpi_debug` — the Batch
42 schema restore works. But the KPI leg itself exhausted
again: `fetched_chars` 31678 (the 99.1 fetched fine),
`workers_ai: TimeoutError`, gateway 7003s, OpenRouter 429s,
`settled_on: "exhausted"`, `replies: 0`. Fine print 0 too.
The story completed on the same model in the same run.

The same prompt, same 6,000-char window, completed on
Workers AI in ~34s at 08:35 MST (12 items, direct call) and
timed out at 60s at 09:57 MST. That is load variance on the
Workers AI free tier's GPU queue, not a prompt defect — and
the gateway/OpenRouter legs are still rate-limited (free-key
quota, persisting since ~12:45 UTC), so there is no other
safety net. Also confirmed from the code: when phase 1
exhausts, `extract_kpis_async` returns early and phase 2
(the diagram) never runs — so an exhausted KPI phase loses
the diagram too.

## Change

The Orchestrator's `_writer_steps` retries the KPI mode call
ONCE when it returns empty on exhaustion (`settled_on`
"exhausted") or when the mode call itself failed (no debug
at all). A clean empty settle — two models agreed the
release has no operating KPIs — is NOT retried. The retry's
result supersedes the first attempt's when it carries items
or a debug dict. Cost: up to ~65s extra on the Writer phase
when the first attempt fails (phase ~230s, run ~245s, inside
the 300s stream gap limit).

Not changed: the timeouts. If both attempts time out, that
is the evidence for a targeted timeout raise (Batch 44
candidate) — the retry is the cheaper experiment first.

## Tests

- Retry fires on exhaustion (order story, kpi, kpi, fineprint;
  the retry's items win).
- No retry on a clean empty settle.
- No retry when the first call returns items.
- Full suite: **275 passed, 1 skipped** (was 272).
