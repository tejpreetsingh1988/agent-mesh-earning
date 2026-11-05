# ADR 060 — Batch 39: per-leg error telemetry on the KPI chain

Date: 2026-11-05. Status: built + tested, upload pending.

## What Batch 38 proved

The diagnostic call (BROS pack, Writer version 30b00dda) returned:

```json
{"fetched_chars": 31678,
 "fetched_url": "https://www.sec.gov/Archives/edgar/data/1866581/000186658126000178/a2026-q3_ex991.htm",
 "settled_on": "exhausted", "replies": 0}
```

- The fetch works: the full 99.1 (31,678 chars) arrives.
- The chain exhausted with **zero model replies** — no empty verdict,
  no garbled JSON, nothing. No `last_parse_ok` / `last_reply_head`
  exists because no reply ever arrived.
- The call took 65.6s total, consistent with the Workers AI leg
  consuming its 60s timeout and the remaining legs failing fast.

The story chain uses the same Workers AI model, gateway routes, and
OpenRouter key and does succeed — so the difference is the KPI prompt
itself (20,000 chars of release text + a long structured-JSON schema).
What is still unknown is HOW each leg fails: Workers AI timeout vs
instant error, gateway 401/404, OpenRouter 429/401. The fix depends
on the answer (prompt size vs a key/route problem), so the chain now
records it.

## Change

`extract_kpis_async` / `extract_kpis_sync` gain a `_fail(leg, exc)`
helper: every failed model call appends
`{"leg": "workers_ai" | "gateway:<model>" | "openrouter:<model>",
  "error": "<Type>: <message>"[:160]}` to `debug["errors"]`.
Error strings name the failure; they never carry a secret (a 401
message is just "HTTP 401"). No other behavior changed — same
settle rule, same timeouts, same hiding result.

## Tests

- New test in `tests/unit/test_kpis.py`: a fake LLM that raises
  for every model yields `replies: 0`, `settled_on: "exhausted"`,
  and an `errors` list naming each leg.
- Full suite: **266 passed, 1 skipped** (was 265).

## Next

Re-run the direct KPI call on BROS's pack against the deployed
Batch 39 Writer and read `kpi_result.debug.errors` — the first
entry (workers_ai) plus the gateway/OpenRouter entries name the
failure mode per leg, and the fix follows from that.
