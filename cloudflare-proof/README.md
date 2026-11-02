# Cloudflare Python Worker proofs — Analyst, then Scout

Goal: prove mesh FastAPI services run on Cloudflare's free Workers
tier (no credit card), one service at a time, lightest first.

Why Analyst first: it never calls a live data source — it computes
only from an EvidencePack — and its only dependencies are FastAPI +
Pydantic + stdlib. No pandas, no yfinance, no network calls. If
Analyst cannot run as a Python Worker, the heavier services will
not either.

Why Scout second: it is the first service that touches the network
(EDGAR, Nasdaq, Motley Fool via urllib) and the first that would
want yfinance/pandas. It is the test of whether a Worker can reach
live sources at all, and of how gracefully it degrades when a
dependency is absent.

## Layout

- `analyst/` is a self-contained Worker project: `wrangler.jsonc`,
  `pyproject.toml`, `src/worker.py`, and `src/mesh/` — a vendored copy of
  the five pure modules Analyst needs (`schemas`, `analyst`, `agent_app`,
  `cards`, `auth`).
- `scout/` is the same shape for Scout: `wrangler.jsonc`,
  `pyproject.toml`, `src/worker.py`, and `src/mesh/` — the core modules
  plus `edgar`, `edgar_facts`, `consensus`, `news`, `transcript`,
  `market`, `direct_client`, and (v2) `worker_http`, `async_tools`,
  `scout_async`. Its worker is derived from `agents/scout/main.py`
  with the handler made async and the MCP client swapped from HTTP
  (`make_client()`) to in-process async (`async_direct_call`): a
  Worker has no sibling MCP services to call, and it cannot do
  synchronous urllib at all (see Scout v2 below).
- The repo root `mesh/` remains the source of truth. Regenerate both
  copies with: `python3 scripts/sync-worker-proof.py`. Never hand-edit
  a copy.
- Each `src/worker.py` is the service's FastAPI app (`/health`,
  `/.well-known/agent.json`, `/tasks/send`) plus
  `Default = asgi.entrypoint(app)` for the Worker runtime. The `workers`
  import is guarded so the same file imports locally for tests.

## Scout v2: sync urllib is dead in Workers — async fetch (pyfetch)

Scout v1 deployed cleanly but its live GOOGL run returned
NOT_REPORTED_YET: the EDGAR fetch died in-Worker ("Remote end
closed connection without response", twice in ~1s). Cloudflare's
docs say Python Workers do not support synchronous requests —
no worker threads, no synchronous XHR — so stdlib urllib cannot
work there, full stop. v2 replaces the transport, not the logic:
`mesh/worker_http.py` fetches via Pyodide's `pyfetch` in a Worker
and via urllib-on-a-thread anywhere else; `mesh/async_tools.py`
mirrors the EDGAR / filing-facts / consensus / transcript tools
as async functions reusing the sync parsers; `mesh/scout_async.py`
mirrors `collect_evidence` with awaits; `mesh/agent_app.py`
gains an async `/tasks/send` endpoint. The sync Docker path is
untouched. The pyfetch path itself can only be proven by the
live Worker deploy — local tests prove the fallback path and
the orchestration parity. See ADR 009.

## Scout v1: yfinance deliberately omitted

Scout's `pyproject.toml` lists only FastAPI + Pydantic. The market
steps (quarterly history, price reaction) then raise inside Scout's
try blocks and land in `pack.missing` instead of failing, while the
stdlib-only EDGAR / Nasdaq / transcript steps carry the pack — and
the EDGAR XBRL overlay already supplies the filing-verified facts,
so the pack's headline numbers do not depend on yfinance anyway.
Whether pywrangler can bundle yfinance (+pandas) into a Worker is a
separate, later experiment; v1 first proves the Worker can reach
EDGAR/Nasdaq/Fool at all via urllib. Read `pack.missing` after a
live Scout run: it names exactly which network steps worked.

## What this proves / does not prove

Analyst (deployed + verified Nov 1, 2026 at
`mesh-analyst-proof.tejpreetsingh1988.workers.dev`): a real mesh
FastAPI service, with its Agent Card and task endpoint, runs on
Workers Free and returns the same Analysis as the Docker service
for the same EvidencePack. Deploy notes that mattered: plain
`wrangler deploy` does NOT bundle Python dependencies — the deploy
command must be `uv run pywrangler deploy` — and the workers.dev
route ships Disabled and must be toggled on under Domains.
Scout (deployed Nov 1, 2026 at
`mesh-scout-proof.tejpreetsingh1988.workers.dev`, v1 verified
partial: /health + Agent Card ok, live GOOGL run failed on sync
urllib — v2 async fetch is the fix, pending redeploy): see above.
Still not proven:
yfinance/pandas in Pyodide, the Streamlit UI (Workers cannot run
Streamlit), SSE streaming through a Worker, or the 9-service
topology over service bindings. Each is a separate, later test.

## Auth note

With no `AGENT_API_TOKEN` secret set, the service accepts requests (auth
is off when the token is unset, same as local dev). For a public proof
URL, set the token with `wrangler secret put AGENT_API_TOKEN` and send
`Authorization: Bearer <token>` — or keep the proof URL private.

## Deploy (Tej does this in his own browser/terminal; no credentials to Muse)

1. Create a Cloudflare account at dash.cloudflare.com with email only —
   no credit card for the free tier.
2. `wrangler login`, then from `cloudflare-proof/analyst/`:
   `wrangler deploy` (or connect the GitHub repo via Workers Builds).
3. Check: `curl https://mesh-analyst-proof.<account>.workers.dev/health`
   then POST an EvidencePack to `/tasks/send` and compare the Analysis
   with the local Docker Analyst for the same pack.
