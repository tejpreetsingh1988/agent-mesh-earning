"""LangChain story client — the Writer's LLM step, via LangChain.

Why this exists, and what it does NOT do:
- The LLM's job is unchanged from mesh/llm.py: write story prose over
  an already Critic-approved Analysis + transcript, nothing else.
  LangChain is the *client* for that one call, not a new Analyst,
  Critic, or Orchestrator. The numbers stay deterministic, and
  validate_story() in mesh/llm.py still gates every story before
  publication, LangChain or not.
- OpenRouter is OpenAI-compatible, so langchain-openai's ChatOpenAI
  points at https://openrouter.ai/api/v1 with the user's
  OPENROUTER_API_KEY. No LangChain API key, no LangSmith, no
  tracing is configured — nothing about a briefing is sent to
  LangChain's services; only the public earnings claims and the
  public transcript excerpt go to the model provider, exactly as
  with the previous direct urllib call.
- The prompt is a LangChain ChatPromptTemplate (system + human),
  the model is a ChatOpenAI runnable, and the response is read
  back as an AIMessage so token usage survives (a StrOutputParser
  would throw usage away, and the UI log needs tokens in/out).
- Imports are lazy, inside run_langchain_story(): if langchain-core
  / langchain-openai are not installed, ImportError propagates and
  mesh/llm.py falls back to its legacy urllib client for that
  model. A provider error (overload, rate limit, 404) is NOT
  swallowed here — it propagates so build_story() can try the
  next model in the fallback chain.
- llm= is injectable for tests: pass any object with .invoke(messages)
  returning an object with .content and .usage_metadata (or
  .response_metadata["token_usage"]), and no network is touched.
"""

import time


def _extract_text(response) -> str:
    content = getattr(response, "content", "") or ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return str(content)


def _extract_usage(response) -> tuple:
    usage = getattr(response, "usage_metadata", None) or {}
    if isinstance(usage, dict) and usage:
        return usage.get("input_tokens"), usage.get("output_tokens")
    meta = getattr(response, "response_metadata", None) or {}
    token_usage = meta.get("token_usage") if isinstance(meta, dict) else None
    if isinstance(token_usage, dict):
        return token_usage.get("prompt_tokens"), token_usage.get("completion_tokens")
    return None, None


def run_langchain_story(model: str, system: str, user: str, api_key: str, llm=None) -> dict:
    """Call one model via LangChain. Returns {text, model, tokens_in,
    tokens_out, latency_s}. Raises on provider/import errors."""
    started = time.monotonic()
    if llm is None:
        # Lazy imports: this module must be importable (and the
        # deterministic path usable) even where LangChain is absent.
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_openai import ChatOpenAI

        template = ChatPromptTemplate.from_messages(
            [("system", "{system}"), ("human", "{user}")]
        )
        messages = template.format_messages(system=system, user=user)
        llm = ChatOpenAI(
            model_name=model,
            openai_api_key=api_key,
            openai_api_base="https://openrouter.ai/api/v1",
            temperature=0.2,
            max_tokens=1800,
            default_headers={
                "HTTP-Referer": "https://example.com/agent-mesh-earnings",
                "X-Title": "Agent Mesh Earnings",
            },
        )
    else:
        # Test path: the injected LLM receives LangChain messages if
        # available, otherwise plain (role, content) tuples.
        try:
            from langchain_core.prompts import ChatPromptTemplate

            messages = ChatPromptTemplate.from_messages(
                [("system", "{system}"), ("human", "{user}")]
            ).format_messages(system=system, user=user)
        except ImportError:
            messages = [("system", system), ("human", user)]
    response = llm.invoke(messages)
    tokens_in, tokens_out = _extract_usage(response)
    return {
        "text": _extract_text(response),
        "model": model,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "latency_s": round(time.monotonic() - started, 1),
    }
