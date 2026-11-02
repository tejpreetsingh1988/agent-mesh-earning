"""Workers AI story source: tried first, falls through on any failure.

Covers mesh/worker_ai.py (response extraction + the one chat call),
mesh/story_async.py's source order (Workers AI -> OpenRouter ->
deterministic), and mesh/worker_env.py's ai_binding() locally
(where the `workers` module does not exist, so it must be None).

Async code is tested with sync defs wrapping asyncio.run, per
this codebase's no-pytest-asyncio convention.
"""
import asyncio

from mesh.analyst import analyse
from mesh.llm import deterministic_story
from mesh.schemas import EvidencePack
from mesh.story_async import build_story_async
from mesh.worker_ai import WORKERS_AI_MODEL, _extract_text, call_workers_ai
from mesh.worker_env import ai_binding


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


class _FakeAI:
    def __init__(self, text=None, error=None, raw=None):
        self.text = text
        self.error = error
        self.raw = raw
        self.calls = []

    async def run(self, model, payload):
        self.calls.append((model, payload))
        if self.error is not None:
            raise RuntimeError(self.error)
        if self.raw is not None:
            return self.raw
        return {"response": self.text}


def test_extract_text_variants():
    assert _extract_text("plain") == "plain"
    assert _extract_text({"response": "dict"}) == "dict"
    assert _extract_text({"result": {"response": "nested"}}) == "nested"
    assert _extract_text({}) == ""
    assert _extract_text(None) == ""

    class Obj:
        response = "attr"
    assert _extract_text(Obj()) == "attr"


def test_call_workers_ai_sends_messages_and_returns_shape():
    async def go():
        return await call_workers_ai(_FakeAI(text="hello"), WORKERS_AI_MODEL, "sys", "usr")
    result = asyncio.run(go())
    assert result["text"] == "hello"
    assert result["model"] == WORKERS_AI_MODEL


def test_workers_ai_valid_story_wins_and_openrouter_not_called():
    pack, analysis = _pack(), analyse(_pack())

    async def exploding_llm(model, system, user):
        raise AssertionError("OpenRouter must not be tried after a valid Workers AI story")

    async def go():
        return await build_story_async(pack, analysis, llm_call=exploding_llm,
                                       ai=_FakeAI(text=_long_story()))
    result = asyncio.run(go())
    assert result["story"] == _long_story()
    assert "Workers AI" in result["model"]
    assert WORKERS_AI_MODEL in result["model"]


def test_workers_ai_invalid_story_falls_through_to_openrouter():
    pack, analysis = _pack(), analyse(_pack())

    async def fake_llm(model, system, user):
        return {"text": _long_story(), "model": "fake-model",
                "tokens_in": 10, "tokens_out": 20, "latency_s": 0.5}

    async def go():
        return await build_story_async(pack, analysis, llm_call=fake_llm,
                                       ai=_FakeAI(text="too short"))
    result = asyncio.run(go())
    assert result["story"] == _long_story()
    assert "fake-model" in result["model"]


def test_workers_ai_error_falls_through_to_deterministic_with_note():
    pack, analysis = _pack(), analyse(_pack())

    async def go():
        return await build_story_async(pack, analysis, llm_call=None, api_key="",
                                       ai=_FakeAI(error="boom"))
    result = asyncio.run(go())
    assert result["story"] == deterministic_story(pack, analysis)
    assert "Workers AI" in result["model"]


def test_no_ai_binding_behaves_as_before():
    pack, analysis = _pack(), analyse(_pack())

    async def go():
        return await build_story_async(pack, analysis, llm_call=None, api_key="")
    result = asyncio.run(go())
    assert "no OPENROUTER_API_KEY" in result["model"]
    assert result["story"] == deterministic_story(pack, analysis)


def test_ai_binding_is_none_locally():
    # The VM has no `workers` module, so the binding must be absent
    # rather than raising — the caller skips the Workers AI attempt.
    assert ai_binding() is None
