# ADR 010 — Full app end to end: five Workers + a Pages frontend

## Decision

The complete briefing runs on Cloudflare's free tier as five
Python Workers plus a static frontend — no Docker, no server,
no credit card:

- mesh-scout-proof (async tools, pyfetch) and
  mesh-analyst-proof (pure compute) already existed.
- mesh-critic-proof: critique_async mirrors critique with
  awaited re-queries via async_direct_call, so the independent
  re-check stays live in-Worker instead of being skipped.
- mesh-writer-proof: build_story_async POSTs to OpenRouter
  directly via worker_http (no LangChain — httpx has no
  working transport in a Worker — and no urllib, which is
  synchronous). Prompt, model chain and validation are
  imported from llm.py, so the story rules cannot drift.
- mesh-orchestrator-proof: run_briefing_async calls the four
  agent Workers over their public workers.dev URLs (true
  agent-to-agent calls, not in-process), with the same Critic
  gate (max 2 attempts) and NOT_REPORTED_YET behaviour as
  Docker. It is CORS-enabled so the browser frontend can
  call it; the other Workers stay same-origin-only.
- Pages frontend (web/): static HTML/CSS/JS, no build step,
  in the repo's paper-and-ink design. One POST to the
  Orchestrator, then it renders the Briefing JSON. No numbers
  are computed in the browser.

## Deliberate limits, stated plainly

- Writer key: the story reads OPENROUTER_API_KEY from the
  process environment, i.e. a secret set on the Writer
  Worker. Cloudflare documents env access via the
  WorkerEntrypoint `env` attribute, NOT os.environ, and the
  asgi adapter does not hand env to the app — so whether
  os.environ surfaces the secret in-Worker is UNPROVEN. The
  live run reveals it in story_model: a model name means
  the key was visible; "deterministic (no OPENROUTER_API_KEY
  configured)" means it was not, and the briefing is still
  complete. The key is never sent from the browser and never
  rides in a Worker-to-Worker payload (those URLs are public
  with auth off). If os.environ proves blind, the follow-up
  is a custom entrypoint that copies env into os.environ
  before delegating to the asgi app — not a key in code.
- Per-model story timeout is 60s in-Worker (Docker: 120s),
  and each agent call is capped at 300s in the Orchestrator,
  so a full briefing can take a few minutes when free
  models are slow. The frontend says so instead of faking
  staged progress: stages are indicative, the request is one
  POST.
- No SSE stream in-Worker (unproven through a Worker); the
  Docker orchestrator keeps its stream.
- yfinance stays out of every Worker bundle, so market
  steps land in pack.missing by design; headline numbers
  come from EDGAR, which is the point.
- Agent Card URLs are still Docker-internal (cosmetic,
  pre-existing).

## Addendum — Error 1042 and the fetch flag (Nov 1, 2026, proven live)

The first end-to-end Orchestrator run failed with HTTP 404
for its Scout call, while the identical Scout request worked
from outside. A temporary probe endpoint on the
Orchestrator showed the truth: from inside a Worker, BOTH
a POST to Scout /tasks/send and a GET to Scout /health
returned Cloudflare "error code: 1042" — the runtime
refuses a Worker fetching another Worker on the same
account as ambiguous same-zone routing. The fix is the
`global_fetch_strictly_public` compatibility flag on the
CALLER's wrangler.jsonc (here, only the Orchestrator's):
it sends sibling calls through the public path. After the
flag deployed, the same probe returned 200 for both calls
and a full REPORTED Scout pack. The flag is therefore
required on any Worker that calls a sibling Worker by its
public workers.dev URL; Workers that only call public
internet hosts (EDGAR, Nasdaq, OpenRouter) do not need it.
Service bindings are the documented alternative, but they
need the WorkerEntrypoint `env`, which the asgi adapter
does not hand to the FastAPI app — so the flag, not a
binding, is the mechanism used here. The probe endpoint
itself was removed after diagnosis; it never shipped in
the final build.
