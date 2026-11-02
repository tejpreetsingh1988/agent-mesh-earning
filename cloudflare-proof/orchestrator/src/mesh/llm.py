"""LLM story layer — OpenRouter, validated, never trusted blindly.

The LLM's ONLY job here is to tie the story together in prose:
what drove the quarter, why the headline numbers and the EPS
story can point in different directions, and what management
signalled on the call. It does no math, no evidence gathering,
and no verification — those stay deterministic (Analyst, Critic).

Models (Oct 29, 2026, live-checked with a real key): primary
nvidia/nemotron-3-ultra-550b-a55b:free, then fallbacks
google/gemma-4-31b-it:free, then cohere/north-mini-code:free.
Ultra was provider-overloaded (503) at check time, Gemma was
upstream rate-limited (429), Cohere answered — so a chain, not a
single fallback, is what makes this work in practice. Nemotron 3
Super :free is NOT in the chain: it returned 404, paid only, on
Oct 29. Ultra's free route does not enforce structured JSON
output, which is fine here because the story is prose, not JSON
— and because the story is validated below, not trusted. Env
overrides: LLM_MODEL_PRIMARY, LLM_MODEL_FALLBACKS,
OPENROUTER_API_KEY (from the host .env in Docker; never in the
repo or a zip).

Validation — the part that makes this safe to ship:
- Every $ amount, % figure, and billion/million quantity in the
  LLM text must appear, as a number, in the verified claims, the
  pack consensus/facts, or the transcript excerpt/takeaways.
  A number that appears nowhere is a hallucination until proven
  otherwise, so the whole LLM story is dropped, not patched.
- Every quoted string must appear verbatim (normalised) in the
  transcript text. An invented quote is the same failure.
- Recommendation language ("price target", "buy rating",
  "recommend buying/selling") fails the story: v1 gives no
  investment advice.
On any validation failure, or if there is no OpenRouter key, or
if both model calls fail, the story is the deterministic fallback
below — verdict + drivers + transcript takeaways, in plain
sentences, with no LLM claim at all. The Briefing records which
path was taken in story_model, so the UI and log never claim a
model wrote something it did not.
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

PRIMARY = os.environ.get("LLM_MODEL_PRIMARY") or "nvidia/nemotron-3-ultra-550b-a55b:free"
# Fallback chain, in order. Oct 29, 2026 live check with a real key:
# - Nemotron 3 Super :free is GONE (404, paid only) — do not use it
#   as the sole fallback, whatever older notes say.
# - Gemma 4 31B :free exists but was upstream rate-limited (429) at
#   check time — transient, worth retrying after Ultra.
# - Cohere North Mini Code :free was the only model that answered
#   consistently in the VM check, so it is the last resort here.
# LLM_MODEL_FALLBACKS (comma-separated) overrides this list;
# the legacy single LLM_MODEL_FALLBACK is tried first if set.
_fallbacks_env = os.environ.get("LLM_MODEL_FALLBACKS")
if _fallbacks_env:
    FALLBACK_MODELS = [s.strip() for s in _fallbacks_env.split(",") if s.strip()]
else:
    _legacy = os.environ.get("LLM_MODEL_FALLBACK")
    FALLBACK_MODELS = ([_legacy] if _legacy else []) + [
        "google/gemma-4-31b-it:free",
        "cohere/north-mini-code:free",
    ]
MODELS = [PRIMARY] + [m for m in FALLBACK_MODELS if m and m != PRIMARY]
API_URL = "https://openrouter.ai/api/v1/chat/completions"

_MONEY_PCT_RE = re.compile(
    r"\$[\d,]+(?:\.\d+)?\s*(?:billion|million|B|M)?|[\d,]+(?:\.\d+)?\s*%|[\d,]+(?:\.\d+)?\s*(?:billion|million)\b",
    re.I)
_NUM_RE = re.compile(r"[\d,]+(?:\.\d+)?")
_QUOTE_RE = re.compile(r'"([^"]{10,})"')
_FORBIDDEN = ("price target", "buy rating", "sell rating", "recommend buying",
              "recommend selling", "we recommend a buy", "we recommend a sell")


def _numbers(text: str) -> set[float]:
    out = set()
    for m in _MONEY_PCT_RE.finditer(text or ""):
        num = _NUM_RE.search(m.group(0))
        if num:
            try:
                out.add(round(float(num.group(0).replace(",", "")), 4))
            except ValueError:
                pass
    return out


def _allowed_numbers(pack, analysis) -> set[float]:
    texts = [c.text for c in (analysis.claims or [])]
    texts += [str(b.get("estimate")) for b in (analysis.beat_miss or []) if b.get("estimate") is not None]
    texts += [str(b.get("actual")) for b in (analysis.beat_miss or []) if b.get("actual") is not None]
    cons = pack.consensus or {}
    for key in ("eps_estimate", "eps_reported", "revenue_usd_b", "revenue_estimate_low_b",
                "revenue_estimate_high_b"):
        if cons.get(key) is not None:
            texts.append(str(cons[key]))
    tr = pack.transcript or {}
    if isinstance(tr, dict):
        texts += list(tr.get("takeaways") or [])
        texts.append(tr.get("summary") or "")
        texts.append(tr.get("excerpt") or "")
    allowed: set[float] = set()
    for t in texts:
        allowed |= _numbers(str(t))
    # Facts themselves (values are in USD_B / USD, claims already
    # carry them formatted, but include them raw as well).
    for f in (pack.facts or []):
        allowed.add(round(float(f.value), 4))
    return allowed


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


MIN_STORY_CHARS = 600
MIN_STORY_PARAGRAPHS = 4


def validate_story(text: str, pack, analysis) -> tuple[bool, str]:
    """Return (ok, reason). A failed story is dropped, never edited."""
    if not text or len(text.strip()) < MIN_STORY_CHARS:
        return False, f"LLM story too short to provide context: {len((text or '').strip())} chars, need at least {MIN_STORY_CHARS}"
    paragraphs = [p.strip() for p in (text or "").split("\n\n") if p.strip()]
    if len(paragraphs) < MIN_STORY_PARAGRAPHS:
        return False, f"LLM story too thin: {len(paragraphs)} paragraphs, need at least {MIN_STORY_PARAGRAPHS}"
    low = text.lower()
    for phrase in _FORBIDDEN:
        if phrase in low:
            return False, f"recommendation language found: {phrase!r}"
    allowed = _allowed_numbers(pack, analysis)
    for m in _MONEY_PCT_RE.finditer(text):
        num = _NUM_RE.search(m.group(0))
        if not num:
            continue
        try:
            val = round(float(num.group(0).replace(",", "")), 4)
        except ValueError:
            continue
        if val not in allowed and not any(abs(val - a) < 0.051 for a in allowed):
            return False, f"number {m.group(0)!r} appears in the LLM story but not in verified claims or the transcript"
    tr = pack.transcript or {}
    transcript_text = ""
    if isinstance(tr, dict):
        transcript_text = _norm(" ".join(tr.get("takeaways") or []) + " " +
                                (tr.get("summary") or "") + " " + (tr.get("excerpt") or ""))
    for quote in _QUOTE_RE.findall(text):
        if transcript_text and _norm(quote) not in transcript_text:
            return False, f"quote {quote[:60]!r} does not appear verbatim in the transcript excerpt"
    return True, ""


def deterministic_story(pack, analysis) -> str:
    """Deterministic story — same length rule as the LLM story.

    This used to be a verdict plus drivers, i.e. 5–8 lines. It now
    restates the whole verified record in prose: verdict, drivers,
    every claim, the call, and the risks to watch, as separate
    paragraphs. No new numbers: every figure comes from a claim,
    a driver, or a transcript takeaway already in the pack."""
    parts = [analysis.verdict_draft]
    if analysis.drivers:
        parts.append("What drove the quarter: " + "; ".join(d.rstrip(".") for d in analysis.drivers) + ".")
    if analysis.claims:
        parts.append("The verified record in full: " + "; ".join(c.text for c in analysis.claims) + ".")
    tr = pack.transcript or {}
    if isinstance(tr, dict) and tr.get("status") == "available" and tr.get("takeaways"):
        parts.append("On the earnings call, management highlighted: " +
                     "; ".join(tr["takeaways"][:5]) + ".")
        parts.append("Those are management's words from the call transcript, not verified results — "
                     "the claims table above is the verified record.")
    elif isinstance(tr, dict) and tr.get("status") != "available":
        parts.append("No earnings-call transcript was available for this quarter, so this story "
                     "is drawn only from the verified claims above.")
    if analysis.risks_and_watch:
        parts.append("What to watch: " + "; ".join(r.rstrip(".") for r in analysis.risks_and_watch) + ".")
    return "\n\n".join(parts)


def _prompt(pack, analysis) -> tuple[str, str]:
    claims = "\n".join(f"- {c.text}" for c in analysis.claims)
    drivers = "; ".join(analysis.drivers) or "none stated by the deterministic Analyst"
    tr = pack.transcript or {}
    transcript_block = "No transcript available."
    if isinstance(tr, dict) and tr.get("status") == "available":
        transcript_block = (
            f"Source: {tr.get('source', 'Motley Fool transcript')} — {tr.get('url', '')}\n"
            f"Takeaways:\n" + "\n".join(f"- {t}" for t in (tr.get("takeaways") or [])[:12]) +
            f"\nSummary: {tr.get('summary', '')}\n"
            f"Prepared-remarks excerpt: {(tr.get('excerpt') or '')[:4000]}")
    system = (
        "You write the story section of an earnings briefing. You MUST use only the numbers "
        "in the verified claims below and in the transcript block. Do not invent, round into, "
        "or paraphrase any other number. Do not quote anyone unless the quote is verbatim in "
        "the transcript block, and attribute it to the speaker. Label anything from the call "
        "as management commentary or guidance, and label guidance as forward-looking, not a "
        "result. Do not give a buy/sell/hold recommendation or a price target. Write 5 to 7 "
        "paragraphs, at least 700 characters, separated by blank lines, in this order: "
        "(1) the headline quarter, (2) what drove revenue and margin, (3) why the operating "
        "story and the EPS story differ, including the EPS basis, (4) what management "
        "signalled on the call, (5) guidance and what to watch, including risks. Plain "
        "language, no marketing copy, no filler — a short 5–8 line summary is a failure.")
    user = (
        f"{pack.company_name} ({pack.ticker}), {pack.quarter_label}.\n\n"
        f"Verdict (deterministic): {analysis.verdict_draft}\n\n"
        f"Verified claims:\n{claims}\n\nDrivers: {drivers}\n\n"
        f"Transcript (management commentary only):\n{transcript_block}\n\n"
        "Now write the story: what drove the quarter, why the operating story and the EPS "
        "story may differ, and what management signalled next. Every number must come from "
        "the claims or the transcript above.")
    return system, user


def _call_openrouter(model: str, system: str, user: str, api_key: str) -> dict:
    # urllib, not httpx: httpx fails in the assistant VM on its egress
    # proxy ("Invalid port") while urllib — already used by mesh/edgar.py
    # for live EDGAR/Nasdaq calls — works. urllib is stdlib, so this
    # also works unchanged in Docker on Windows.
    started = time.monotonic()
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.2,
        "max_tokens": 1800,
    }).encode("utf-8")
    req = urllib.request.Request(API_URL, data=payload, headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://example.com/agent-mesh-earnings",
        "X-Title": "Agent Mesh Earnings",
    }, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="ignore")[:300]
        raise RuntimeError(f"OpenRouter HTTP {e.code}: {detail}") from e
    # OpenRouter can return HTTP 200 with a top-level "error" (e.g.
    # provider overloaded, 503 inside the body). That is a failed
    # call, not an empty story — raise so the fallback model is tried.
    if isinstance(body, dict) and body.get("error"):
        err = body["error"]
        raise RuntimeError(f"OpenRouter error {err.get('code', '')}: {err.get('message', '')}")
    text = (body.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
    usage = body.get("usage") or {}
    return {"text": text, "model": model,
            "tokens_in": usage.get("prompt_tokens"), "tokens_out": usage.get("completion_tokens"),
            "latency_s": round(time.monotonic() - started, 1)}


def _call_langchain_or_legacy(model: str, system: str, user: str, api_key: str) -> dict:
    """Primary story call: LangChain (mesh/langchain_story.py).

    Only a missing LangChain install falls back to the legacy
    urllib client — and only for that model. A provider error from
    LangChain propagates, so build_story() moves to the next model
    in the chain instead of silently retrying the same model twice
    through a different client."""
    try:
        from .langchain_story import run_langchain_story
    except ImportError:
        return _call_openrouter(model, system, user, api_key)
    try:
        return run_langchain_story(model, system, user, api_key)
    except ImportError:
        return _call_openrouter(model, system, user, api_key)


def build_story(pack, analysis, llm_call=None, api_key: str | None = None) -> dict:
    """Return {story, model, tokens_in, tokens_out, latency_s}.

    llm_call(model, system, user) -> dict is injected by tests; in
    production it defaults to the real OpenRouter call. If there is
    no key, or the call fails, or validation fails, the story is
    deterministic and model says so — never a silent LLM claim."""
    key = api_key if api_key is not None else os.environ.get("OPENROUTER_API_KEY", "")
    system, user = _prompt(pack, analysis)
    if llm_call is None and not key:
        return {"story": deterministic_story(pack, analysis),
                "model": "deterministic (no OPENROUTER_API_KEY configured)",
                "tokens_in": None, "tokens_out": None, "latency_s": None}
    caller = llm_call or (lambda model, s, u: _call_langchain_or_legacy(model, s, u, key))
    errors: list[str] = []
    for model in MODELS:
        try:
            result = caller(model, system, user)
        except Exception as e:
            errors.append(f"{model}: {e}")
            continue
        text = (result or {}).get("text", "") or ""
        ok, reason = validate_story(text, pack, analysis)
        if not ok:
            # A bad story from one model is NOT a final failure — it
            # is a reason to try the next model in the chain. The old
            # code returned deterministic here, so a too-short reply
            # from the first model that answered (e.g. Ultra returning
            # empty content) never reached Gemma or Cohere. Only after
            # every model has failed does the deterministic story ship,
            # with every model's failure listed in the model note.
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
