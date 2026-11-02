"""Async LLM story for the Writer Worker — no LangChain, no urllib.

Why a separate path: the Docker story call goes through LangChain
(httpx) or legacy urllib, and neither works in a Python Worker —
httpx has no working transport there and urllib is synchronous
(see mesh/worker_http.py). The Worker story is therefore a direct
POST to OpenRouter's chat/completions endpoint via worker_http,
with the same prompt, the same model chain, and the same
validation as mesh/llm.py (all three are imported, not copied).
Anything else — no key, a failed call, a failed validation —
falls back to the deterministic story, with the model note saying
so, exactly like build_story.

Key handling, stated plainly: the key is read from
OPENROUTER_API_KEY in the process environment. In a Worker that
means a secret set on the Worker (dashboard: Settings →
Variables → Secrets, or `wrangler secret put`). Whether the
Python Worker runtime surfaces secrets into os.environ is NOT
proven — the live Writer run will show it in story_model: a
model name means the key was visible; "deterministic (no
OPENROUTER_API_KEY configured)" means it was not, and the
briefing is still complete, just without an LLM story. The key
is never sent from the browser and never appears in a request
payload between Workers.

Per-model timeout is 60s here (Docker uses 120s): a demo
briefing should fail over to the next model — or to the
deterministic story — rather than hang the page.
"""
import asyncio
import os
import time

from .llm import (
    API_URL,
    MODELS,
    PRIMARY,
    _prompt,
    deterministic_story,
    validate_story,
)
from .worker_http import post_json

MODEL_TIMEOUT_S = 60


async def _call_openrouter_async(model: str, system: str, user: str, api_key: str) -> dict:
    started = time.monotonic()
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.2,
        "max_tokens": 1800,
    }
    body = await post_json(API_URL, payload, headers={
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://example.com/agent-mesh-earnings",
        "X-Title": "Agent Mesh Earnings",
    })
    if isinstance(body, dict) and body.get("error"):
        err = body["error"]
        raise RuntimeError(f"OpenRouter error {err.get('code', '')}: {err.get('message', '')}")
    text = (body.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
    usage = body.get("usage") or {}
    return {"text": text, "model": model,
            "tokens_in": usage.get("prompt_tokens"), "tokens_out": usage.get("completion_tokens"),
            "latency_s": round(time.monotonic() - started, 1)}


async def build_story_async(pack, analysis, llm_call=None, api_key: str | None = None) -> dict:
    """Async twin of llm.build_story. llm_call(model, system, user)
    -> awaitable dict is injected by tests; in production it
    defaults to the direct OpenRouter POST above."""
    key = api_key if api_key is not None else os.environ.get("OPENROUTER_API_KEY", "")
    system, user = _prompt(pack, analysis)
    if llm_call is None and not key:
        return {"story": deterministic_story(pack, analysis),
                "model": "deterministic (no OPENROUTER_API_KEY configured)",
                "tokens_in": None, "tokens_out": None, "latency_s": None}
    caller = llm_call or (lambda model, s, u: _call_openrouter_async(model, s, u, key))
    errors: list[str] = []
    for model in MODELS:
        try:
            result = await asyncio.wait_for(caller(model, system, user), timeout=MODEL_TIMEOUT_S)
        except Exception as e:
            errors.append(f"{model}: {e}")
            continue
        text = (result or {}).get("text", "") or ""
        ok, reason = validate_story(text, pack, analysis)
        if not ok:
            errors.append(f"{model}: validation failed: {reason}")
            continue
        note = " (fallback model)" if model != PRIMARY else ""
        return {"story": text.strip(),
                "model": f"{result.get('model', model)}{note}",
                "tokens_in": result.get("tokens_in"), "tokens_out": result.get("tokens_out"),
                "latency_s": result.get("latency_s")}
    return {"story": deterministic_story(pack, analysis),
            "model": f"deterministic (LLM calls failed: {'; '.join(errors)[:300]})",
            "tokens_in": None, "tokens_out": None, "latency_s": None}
