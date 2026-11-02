# ADR 015 — Workers AI as the Writer's first story source

## Status
Accepted Nov 2, 2026. Code + tests built locally; upload and live
verification pending the observability builds (one batch at a time).

## Context
Nov 2, 2026 briefings kept landing on the deterministic story
because all three OpenRouter free models failed in the same run:
Nemotron returning 0 chars, Gemma HTTP 429, Cohere too short to
pass validation — while the same code produced real LLM stories
on other runs. The failure strings prove the key reaches the
Writer; the models are the variance. The deterministic fallback
is correct behavior, but a story source that fails most runs
is a bad default.

## Decision
Try Workers AI first in `build_story_async`, before the
OpenRouter chain:
- New `mesh/worker_ai.py`: `call_workers_ai(ai, model, system,
  user)` — one chat call against the `env.AI` binding, same
  result shape as the OpenRouter call, same prompt, same
  `validate_story` gate.
- New `mesh/worker_env.py::ai_binding()`: reads `env.AI` from
  the Worker env object (guarded, None locally), mirroring the
  secret-reading pattern from ADR 011.
- Writer proof wiring (via `scripts/sync-worker-proof.py`):
  `ai=ai_binding()` passed to `build_story_async`, and
  `"ai": {"binding": "AI"}` added to the Writer proof's
  `wrangler.jsonc`. No other Worker needs the binding.
- Model: `@cf/meta/llama-3.1-8b-instruct` — not one of the
  seven frontier models requiring a paid billing method, and
  at ~490 replies/day of this size inside the free 10,000
  neurons/day allowance, the cheapest plausible story writer.
  Step-ups if validation fails repeatedly: Llama 3.3 70B
  (~83/day), then gpt-oss-120b (far fewer/day) — same code,
  only the model name changes.
- Failure contract: any Workers AI failure (missing binding,
  exception, validation failure) is recorded and falls through
  to the OpenRouter chain, then to the deterministic story.
  The story_model label names the source that actually wrote
  the story (`... (Workers AI)`), so a briefing never pretends
  a Workers AI story happened when it did not.

## Consequences
- No key involved in the first attempt: nothing to rotate,
  nothing to leak, no third-party free-tier lottery.
- OpenRouter stays as fallback, so a Workers AI outage
  degrades to today's behavior instead of breaking briefings.
- Neuron budget is shared across all Workers AI use on the
  account; at a handful of briefings/day this is negligible,
  and the Vectorize embedding batch (next) will share it —
  both stay far inside 10,000/day at current volume.
- The binding cannot be proven locally (no `workers` module,
  no edge runtime in the VM). The proof is live: a briefing
  whose story_model names the Llama model. If it never
  appears, the fallback chain proves the wiring failed safe.

## Verification
After deploy: run briefings until one carries a Workers AI
story_model (or several deterministic ones whose notes name a
Workers AI failure — that outcome proves the attempt ran and
fell through honestly, and means the model choice needs
revisiting, not the wiring).
