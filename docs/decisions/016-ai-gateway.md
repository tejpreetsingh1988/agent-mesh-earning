# ADR 016 — AI Gateway in front of OpenRouter

## Status
Accepted Nov 2, 2026. Code + tests built locally; dashboard
steps (gateway creation, BYOK key, gateway URL variable) and
live verification pending.

## Context
Workers AI is now the first story source and works (three
consecutive live briefings, Nov 2, 2026). OpenRouter remains
the fallback chain, and it still has the old shape: the
Writer holds the OpenRouter key as a Secret, calls OpenRouter
directly, and nothing is cached or logged centrally. AI
Gateway fixes all three without changing the story logic:
one place for the key, analytics on every fallback call, and
caching so a repeated briefing does not re-spend a model
call.

## Decision
- The OpenRouter fallback in `build_story_async` is routed
  via AI Gateway when a `GATEWAY_OPENROUTER_URL` variable is
  set, and direct otherwise. The variable holds the FULL
  gateway endpoint:
  `https://gateway.ai.cloudflare.com/v1/{account_id}/{gateway_id}/openrouter/chat/completions`
  (the docs' "URL structure" replacement for
  `https://openrouter.ai/api/v1/chat/completions`; the same
  page's curl example shows a `/v1/` variant —
  `.../openrouter/v1/chat/completions` — which is the
  fallback to try first if the no-`/v1/` form 404s live).
- With a gateway, NO Authorization header is sent: the
  gateway's stored provider key (BYOK, Secrets Store backed)
  supplies the OpenRouter key. The Writer Worker then holds
  no OpenRouter key at all for the fallback path.
- The variable is set in the Cloudflare dashboard on
  mesh-writer-proof, NEVER baked into the repo's
  wrangler.jsonc: account_id and gateway name are
  identifiers, not secrets, but there is no reason to
  publish them in a public repo.
- The gateway's OpenRouter provider key is entered by Tej
  himself in the dashboard (AI > AI Gateway > gateway >
  Provider Keys > Add API Key). The assistant never sees,
  handles, or routes the key value.
- The story_model label gains "(via AI Gateway)" when the
  gateway wrote the story, so gateway use is visible in the
  briefing itself, not only in gateway analytics.
- Docker path unchanged: no gateway variable there, so it
  keeps calling OpenRouter direct with the host .env key.
  Gateway routing is a Worker-path concern only, for now.

## Consequences
- Fallback calls gain analytics and caching with zero
  story-logic changes: same models, same prompt, same
  validation, same deterministic fallback.
- Key hygiene improves: one stored key in the gateway
  instead of a Secret on the Writer, and the key stops
  travelling from the Worker on every fallback call.
- Caching is a gateway-side setting. A repeated briefing
  for the same ticker may then return a cached story — the
  story is still validated the same way, but its freshness
  is the gateway's cache TTL, not the briefing time. Worth
  stating plainly if a cached story ever looks stale.
- If the gateway is misconfigured (wrong URL, missing
  provider key), the fallback chain fails exactly as an
  OpenRouter failure does today and the deterministic story
  covers it. A gateway outage degrades, never breaks.

## Verification
1. Gateway created; OpenRouter BYOK key stored (dashboard).
2. GATEWAY_OPENROUTER_URL variable set on mesh-writer-proof.
3. Writer build with gateway-aware code goes live.
4. A briefing whose story falls back to OpenRouter carries
   "(via AI Gateway)" and appears in gateway analytics.
5. A repeat briefing for the same ticker shows a gateway
   cache hit while the story still validates.

## Addendum — HTTPS path replaced by the Worker binding (Nov 2, 2026)

The HTTPS path above was built, uploaded, and deployed — and
then proven broken live. A no-auth POST to the gateway
endpoint (both URL forms) returned HTTP 401 AiGatewayError
2009. The dashboard check found why: the agent-mesh gateway
has "Authenticated Gateway" ON, so plain HTTP needs a gateway
token the Worker does not have. The stored OpenRouter key was
never the problem — it covers the provider credential, not
gateway access — and the key entry itself showed Configured
with no warning.

The fix is the Worker binding, chosen by Tej over a gateway
token secret and over turning gateway auth off. The Writer
already holds the `env.AI` binding (from the Workers AI
batch); no new binding is declared. The OpenRouter chain now
runs through dynamic routes on the gateway — story-nemotron,
story-gemma, story-cohere, one per model in the chain, so
fallback order is preserved — called as
`ai.run("dynamic/<route>", payload, {"gateway": {"id":
"agent-mesh"}})` from new `mesh/gateway_binding.py`. A binding
call is authenticated automatically, and the gateway then
resolves the provider credential in its documented order:
request key, stored `default`-alias key, Unified Billing. The
stored OpenRouter key fires, so no Cloudflare credits are
involved. Dynamic routes also sidestep the naming problem:
`env.AI.run` addresses third-party models as
`{author}/{model}`, and OpenRouter hosts every author's
models, so no such spelling is unambiguous for an OpenRouter
model; the route name is ours and the provider+model mapping
lives in the dashboard.

Consequences: `build_story_async` no longer takes
`gateway_url`, and the HTTPS gateway code is removed (the
GATEWAY_OPENROUTER_URL Worker variable is left set, unused
and harmless). The direct OpenRouter chain with the Writer
secret stays as the last LLM resort. The story label
"(via AI Gateway)" now means a binding route wrote the
story. Cache Responses was OFF at diagnosis; enabling it is
part of this batch's dashboard steps, since the original
caching claim depends on it. Tests: the old HTTPS tests are
replaced by `tests/unit/test_gateway_binding.py` (route
mapping, gateway id in run options, fall-through to direct
and to deterministic). Live proof still needs a natural
fallback — Workers AI must fail first — so the label and the
gateway analytics entry are verified by briefing runs, not
claimed from the deploy.
