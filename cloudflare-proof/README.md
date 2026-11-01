# Cloudflare Python Worker proof — Analyst service

Goal: prove ONE FastAPI service from the mesh runs on Cloudflare's free
Workers tier (no credit card), before porting anything else.

Why Analyst first: it is the lightest service. It never calls a live data
source — it computes only from an EvidencePack — and its only dependencies
are FastAPI + Pydantic + stdlib. No pandas, no yfinance, no network calls.
If Analyst cannot run as a Python Worker, the heavier services will not
either; if it can, Scout (network + yfinance/pandas) is the next, harder test.

## Layout

- `analyst/` is a self-contained Worker project: `wrangler.jsonc`,
  `pyproject.toml`, `src/worker.py`, and `src/mesh/` — a vendored copy of
  the five pure modules Analyst needs (`schemas`, `analyst`, `agent_app`,
  `cards`, `auth`).
- The repo root `mesh/` remains the source of truth. Regenerate the copy with:
  `python3 scripts/sync-worker-proof.py` (copies the five files + the
  worker entrypoint). Never hand-edit the copy.
- `src/worker.py` is the Analyst FastAPI app (`/health`,
  `/.well-known/agent.json`, `/tasks/send`) plus
  `Default = asgi.entrypoint(app)` for the Worker runtime. The `workers`
  import is guarded so the same file imports locally for tests.

## What this proves / does not prove

Proves (once deployed): a real mesh FastAPI service, with its Agent Card
and task endpoint, runs on Workers Free and returns the same Analysis as
the Docker service for the same EvidencePack.
Does NOT prove: Scout (yfinance/pandas in Pyodide), the Streamlit UI
(Workers cannot run Streamlit), SSE streaming through a Worker, or the
9-service topology over service bindings. Each is a separate, later test.

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
