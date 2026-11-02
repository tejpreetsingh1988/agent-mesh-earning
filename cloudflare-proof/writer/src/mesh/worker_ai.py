"""Workers AI as a story source for the Writer Worker — no key, no HTTP.

Why this module exists: the OpenRouter free-model chain is the
weakest link in the live app. On Nov 2, 2026, briefings kept
landing on the deterministic story because all three free models
failed in the same run — Nemotron returning 0 chars, Gemma HTTP
429, Cohere too short to pass validation — while the same code
produced real LLM stories on other runs. That is free-tier
variance, not a configuration problem: the key reaches the
Writer (the failure strings name the models), the models just
do not answer reliably.

Workers AI changes the failure mode. It is a binding, not an
API key: the Worker declares `"ai": {"binding": "AI"}` in its
wrangler config and calls `env.AI.run(model, payload)` — no
secret to store, no third-party rate limit, no key lottery.
The binding is read from the Worker env object the same way
mesh/worker_env.py reads secrets (see ai_binding there), so
locally — where the `workers` module does not exist — this
whole path is simply absent and the OpenRouter chain runs
unchanged.

Model choice: `@cf/meta/llama-3.1-8b-instruct-fp8`. It is NOT
one of the seven frontier models that require a paid billing
method (Kimi K2.6/K2.7, GLM 5.2/5.3/5.3-flash, DeepSeek V4
Flash/Pro), and at ~490 replies/day of this size on the free
10,000-neuron allowance it is the cheapest model that can
plausibly write a validated story. If it fails validation
repeatedly in production, the next step up is Llama 3.3 70B
(~83/day) or gpt-oss-120b (far fewer/day) — same code, only
the model name changes.

Model-ID churn, learned Nov 2, 2026: the first choice,
`@cf/meta/llama-3.1-8b-instruct` (no -fp8 suffix), returned
AiError 5028 live — deprecated on 2026-05-30 — even though
older write-ups still cite it. The FP8-quantized variant is
the live catalog entry as of Nov 2, 2026. Model IDs are
therefore verified against the current catalog
(developers.cloudflare.com/workers-ai/models) and by a live
proof briefing, never from memory or older articles.

Failure contract, stated plainly: a Workers AI failure — a
missing binding, a raised exception, a validation failure —
never breaks the briefing. build_story_async records it and
falls through to the OpenRouter chain, then to the
deterministic story, exactly as an OpenRouter failure does
today. The story_model label says which source actually
wrote the story, so a briefing never pretends a Workers AI
story happened when it did not.
"""

import time

WORKERS_AI_MODEL = "@cf/meta/llama-3.1-8b-instruct-fp8"
WORKERS_AI_TIMEOUT_S = 60


def _extract_text(raw) -> str:
    """Pull the generated text out of a Workers AI response,
    whatever shape it arrives in: a plain string, a dict with
    "response", a dict with result.response, or an object with
    a .response attribute. Anything else yields "" — and an
    empty story fails validation downstream, which is the
    correct outcome for an empty model reply."""
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        text = raw.get("response")
        if isinstance(text, str):
            return text
        result = raw.get("result")
        if isinstance(result, dict) and isinstance(result.get("response"), str):
            return result["response"]
        return ""
    text = getattr(raw, "response", None)
    return text if isinstance(text, str) else ""


def _extract_usage(raw):
    if isinstance(raw, dict):
        usage = raw.get("usage")
        if isinstance(usage, dict):
            return usage.get("prompt_tokens"), usage.get("completion_tokens")
    return None, None


async def call_workers_ai(ai, model: str, system: str, user: str) -> dict:
    """One Workers AI chat call, in the same result shape as
    story_async._call_openrouter_async (text, model, tokens_in,
    tokens_out, latency_s) so build_story_async can try it first
    and fall through to OpenRouter unchanged on failure.

    `ai` is the Workers AI binding (env.AI): an object with an
    async .run(model, payload). Llama instruct models take a
    messages payload. Any exception propagates to the caller,
    which records it and moves on.
    """
    started = time.monotonic()
    payload = {
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": 0.2,
        "max_tokens": 1800,
    }
    raw = await ai.run(model, payload)
    tokens_in, tokens_out = _extract_usage(raw)
    return {"text": _extract_text(raw), "model": model,
            "tokens_in": tokens_in, "tokens_out": tokens_out,
            "latency_s": round(time.monotonic() - started, 1)}
