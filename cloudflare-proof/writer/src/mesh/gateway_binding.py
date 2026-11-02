"""OpenRouter fallback through AI Gateway via the Worker binding.

Why this module exists, and why it replaced the first gateway
attempt: the first attempt (ADR 016) POSTed to the gateway's
HTTPS endpoint with no Authorization header, on the assumption
that a stored provider key (BYOK) would make that work. It does
not: the agent-mesh gateway has "Authenticated Gateway" ON, so
plain HTTP requests without a gateway token get HTTP 401 at the
gateway door, before OpenRouter is ever involved (proven live
Nov 2, 2026 — both URL forms 401'd). The stored key is fine;
it only covers the provider credential, not gateway access.

The binding fixes the auth side. A Worker calling through the
`env.AI` binding is authenticated automatically — no token, no
header, nothing exposed — and the gateway then resolves the
provider credential in its documented order: a key on the
request, then the gateway's stored key (the `default` alias),
then Unified Billing. Our gateway holds a stored OpenRouter
key, so a binding call lands on step two: our key, our
OpenRouter account, no Cloudflare credits involved. (If no key
were stored, the call would fall to Unified Billing — which is
why the gateway's "Require provider credentials" setting
exists, to close that door. It is OFF here; with a key stored
it is not load-bearing, and with no card on the account
Unified Billing could not charge anyway.)

Why dynamic routes: `env.AI.run` addresses third-party models
as `{author}/{model}`, and OpenRouter hosts every author's
models, so there is no unambiguous `{author}/{model}` spelling
for an OpenRouter model. A dynamic route sidesteps the naming
question entirely: the route name is ours, and the
provider+model mapping lives in the gateway dashboard
(story-nemotron / story-gemma / story-cohere, one per model
in the chain, so the code's fallback order is preserved).
Dynamic routes accept the OpenAI chat-completions request
shape, which is what the OpenRouter call already uses.

Failure contract: same as every other story source — an
exception or a validation failure is recorded by
build_story_async and falls through to the next source, never
breaking the briefing. The story_model label says
"(via AI Gateway)" only when a binding route actually wrote
the story.
"""

import time

from .worker_ai import _extract_text, _extract_usage

GATEWAY_ID = "agent-mesh"
GATEWAY_TIMEOUT_S = 60

# OpenRouter model -> dynamic route on the agent-mesh gateway.
# The route names are dashboard configuration, not secrets.
GATEWAY_ROUTES = {
    "nvidia/nemotron-3-ultra-550b-a55b:free": "story-nemotron",
    "google/gemma-4-31b-it:free": "story-gemma",
    "cohere/north-mini-code:free": "story-cohere",
}


def _extract_binding_text(raw) -> str:
    """Text from a binding response: Workers AI shape first
    (response / result.response), then the OpenAI shape a
    dynamic route returns (choices[0].message.content)."""
    text = _extract_text(raw)
    if text:
        return text
    if isinstance(raw, dict):
        choices = raw.get("choices") or []
        if choices:
            message = (choices[0] or {}).get("message") or {}
            content = message.get("content") or (choices[0] or {}).get("text") or ""
            if isinstance(content, str):
                return content
    return ""


async def call_gateway_binding(ai, model: str, system: str, user: str) -> dict:
    """One story call through the AI Gateway binding, in the
    same result shape as worker_ai.call_workers_ai so
    build_story_async can chain it unchanged.

    `ai` is the Workers AI binding (env.AI). The third argument
    to run() scopes the call to the agent-mesh gateway; the
    binding authenticates the Worker, and the gateway supplies
    the stored OpenRouter key. Any exception propagates to the
    caller, which records it and moves on.
    """
    route = GATEWAY_ROUTES.get(model)
    if route is None:
        raise RuntimeError(f"no gateway route for model {model}")
    started = time.monotonic()
    payload = {
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": 0.2,
        "max_tokens": 1800,
    }
    raw = await ai.run(f"dynamic/{route}", payload, {"gateway": {"id": GATEWAY_ID}})
    tokens_in, tokens_out = _extract_usage(raw)
    return {"text": _extract_binding_text(raw), "model": model,
            "tokens_in": tokens_in, "tokens_out": tokens_out,
            "latency_s": round(time.monotonic() - started, 1)}
