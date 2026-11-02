# ADR 014 — Workers Observability on all five Workers

## Status
Accepted Nov 2, 2026. Config change only; no code change.

## Context
Debugging the live app so far has been blind: when a Worker served old code
(the Critic dbd6ac1 anomaly) or a model chain failed (the Writer's
thin/empty/429 failures), there was no server-side record to inspect —
only the briefing output and the dashboard's deployment list. The
streaming log shows pipeline stages to the user, but it is not a
server-side log.

## Decision
Add `"observability": { "enabled": true }` to all five proof Workers'
`wrangler.jsonc` files (scout, analyst, critic, writer, orchestrator).
This enables Workers Logs: invocation metadata, console output, and
exceptions with stack traces, queryable in the dashboard, plus the beta
traces of Worker-to-Worker fetch spans. No binding, no code change, no
dashboard toggle — the flag takes effect on the next deploy of each
Worker.

## Consequences
- Every briefing now leaves a server-side trace: which Worker versions
  ran, how long each stage took, and what failed. The next "serving old
  code" suspicion can be settled from logs instead of discriminating
  probes alone.
- Free-plan limits: 200,000 logs/day, 3-day retention. Briefing volume
  is a handful per day, so this is far inside the allowance.
- **Pricing watch-out:** from Dec 1, 2026, Workers Logs and traces are
  billed under Cloudflare Observability pricing. At current volume the
  free allowance covers it, but if briefing volume grows, lower
  `head_sampling_rate` (e.g. 0.1) instead of disabling observability
  outright.
- The flag was deliberately kept minimal (`enabled: true` only). If the
  dashboard shows logs but no fetch traces, a follow-up change can add
  the traces subkey explicitly.

## Verification
After deploy: run one briefing, then confirm in each Worker's dashboard
Logs view that invocations appear with timestamps and durations.
