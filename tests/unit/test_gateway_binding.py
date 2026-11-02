"""AI Gateway fallback via the Worker binding (dynamic routes).

Covers mesh/gateway_binding.py and its place in
mesh/story_async.py's chain: Workers AI first, then the same
model chain through binding routes (dynamic/story-<model> on
the agent-mesh gateway, gateway id passed in the run options),
then direct OpenRouter, then deterministic. The binding fake
returns the OpenAI choices shape a dynamic route returns; a
binding failure for every route falls through to the direct
chain, never breaking the briefing.

The fake binding's run() takes the same (model, payload,
options) shape as the real env.AI.run. Async code is tested
with sync defs wrapping asyncio.run, per this codebase's
no-pytest-asyncio convention.
"""
import asyncio

from mesh.analyst import analyse
from mesh.llm import MODELS
from mesh.schemas import EvidencePack
from mesh.story_async import build_story_async


def _pack():
    src = {"url": "", "publisher": "yfinance quarterly_financials (unofficial)",
           "retrieved_at": "2026-10-28T16:00:00Z"}

    def fact(fid, metric, value, period):
        return {"id": fid, "metric": metric, "value": value, "unit": "USD_B",
                "period": period, "source": src}
    return EvidencePack(
        ticker="GOOGL", company_name="Alphabet Inc.", quarter_label="Q3 2026",
        quarter_end="2026-09-30", report_date="2026-10-28T16:00:00Z", status="REPORTED",
        facts=[fact("rev_2025", "total_revenue", 102.3, "2025-09-30"),
               fact("rev_2026", "total_revenue", 127.6, "2026-09-30"),
               fact("opinc_2025", "operating_income", 31.2, "2025-09-30"),
               fact("opinc_2026", "operating_income", 40.6, "2026-09-30")],
        consensus={"status": "available", "eps_estimate": 2.94, "eps_reported": 2.12,
                   "source": "Nasdaq earnings calendar"},
        transcript={"status": "available", "source": "Motley Fool (public transcript page)",
                    "url": "https://www.fool.com/earnings/call-transcripts/2026/10/29/alphabet-googl-q3-2026-earnings-call-transcript/",
                    "takeaways": ["Revenue -- $127.6 billion, representing 25% year-over-year growth.",
                                  "Google Cloud Backlog -- $561 billion."],
                    "summary": "Alphabet reported a 25% revenue increase, driven by Cloud.",
                    "excerpt": "Sundar Pichai: Q3 was a strong quarter for Alphabet. Cloud revenues grew 103%."},
    )


def _long_story():
    return "\n\n".join([
        "Revenue grew 24.7% year over year to $127.6 billion in the quarter, and operating "
        "margin reached 31.8%, so the headline quarter was one of strong top-line growth "
        "with profitability holding up alongside it.",
        "Operating income rose from $31.2 billion to $40.6 billion, which is why margin stayed "
        "at 31.8% even as revenue grew to $127.6 billion, and that operating strength is the "
        "core of the quarter's story.",
        "EPS told a different story, missing consensus by 27.9%, with reported EPS of $2.12 "
        "against an estimate of $2.94, so the EPS comparison must be read on its stated basis "
        "and not mixed with the operating picture.",
        "On the earnings call, management highlighted revenue of $127.6 billion, representing "
        "25% year-over-year growth, and a Cloud backlog of $561 billion, with Cloud revenues "
        "growing 103% in the prepared remarks.",
        "What to watch is whether the operating strength shown by revenue growth of 24.7% and "
        "margin of 31.8% carries into the next quarter, and whether the EPS gap of 27.9% "
        "against the $2.94 estimate narrows as the reported $2.12 figure is put in context.",
    ])


class _BindingAI:
    """Fake env.AI: Workers AI models fail (so the chain reaches
    the binding leg), dynamic routes answer or fail per route."""

    def __init__(self, fail_routes=()):
        self.calls = []
        self.fail_routes = set(fail_routes)

    async def run(self, model, payload, options=None):
        self.calls.append((model, payload, options))
        if model.startswith("dynamic/"):
            if model in self.fail_routes:
                raise RuntimeError("binding boom")
            return {"choices": [{"message": {"content": _long_story()}}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 50}}
        raise RuntimeError("no workers ai in this fake")


async def _direct(model, system, user):
    return {"text": _long_story(), "model": model,
            "tokens_in": 10, "tokens_out": 5, "latency_s": 0.1}


def _run(ai, **kwargs):
    pack, analysis = _pack(), analyse(_pack())
    return asyncio.run(build_story_async(pack, analysis, ai=ai, **kwargs))


def test_binding_route_success_labels_gateway():
    ai = _BindingAI()
    result = _run(ai, api_key="dummy-key")
    assert result["story"] == _long_story()
    assert "(via AI Gateway)" in result["model"]
    assert MODELS[0] in result["model"]
    route_calls = [c for c in ai.calls if c[0].startswith("dynamic/")]
    assert route_calls[0][0] == "dynamic/story-nemotron"
    assert route_calls[0][2] == {"gateway": {"id": "agent-mesh"}}


def test_binding_falls_to_next_route_on_failure():
    ai = _BindingAI(fail_routes={"dynamic/story-nemotron"})
    result = _run(ai, api_key="dummy-key")
    assert result["story"] == _long_story()
    assert "(via AI Gateway)" in result["model"]
    assert "(fallback model)" in result["model"]
    assert MODELS[1] in result["model"]


def test_binding_failure_falls_through_to_direct():
    ai = _BindingAI(fail_routes={"dynamic/story-nemotron", "dynamic/story-gemma",
                                 "dynamic/story-cohere"})
    result = _run(ai, api_key="dummy-key", llm_call=_direct)
    assert result["story"] == _long_story()
    assert "(via AI Gateway)" not in result["model"]


def test_binding_failure_without_key_is_deterministic():
    ai = _BindingAI(fail_routes={"dynamic/story-nemotron", "dynamic/story-gemma",
                                 "dynamic/story-cohere"})
    result = _run(ai, api_key="")
    assert result["model"].startswith("deterministic")
    assert "Gateway" in result["model"]
