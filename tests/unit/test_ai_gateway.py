"""AI Gateway routing for the OpenRouter fallback chain.

Covers mesh/story_async.py's gateway_url path: with a gateway
URL the POST goes to the gateway with NO Authorization header
(BYOK supplies the key); without one it goes direct with the
key header, exactly as before. The gateway response is the
OpenRouter response shape (the gateway preserves the provider
schema), so the same parsing and validation apply.

post_json is monkeypatched — no network. Async code is tested
with sync defs wrapping asyncio.run, per this codebase's
no-pytest-asyncio convention.
"""
import asyncio

import mesh.story_async as story_async
from mesh.analyst import analyse
from mesh.llm import API_URL
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


class _Capture:
    def __init__(self):
        self.calls = []

    async def post_json(self, url, payload, headers=None):
        self.calls.append((url, headers or {}))
        return {"choices": [{"message": {"content": _long_story()}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50}}


def _run_with_capture(capture, **kwargs):
    pack, analysis = _pack(), analyse(_pack())
    old = story_async.post_json
    story_async.post_json = capture.post_json
    try:
        return asyncio.run(build_story_async(pack, analysis, **kwargs))
    finally:
        story_async.post_json = old


def test_gateway_route_posts_to_gateway_without_auth_header():
    capture = _Capture()
    result = _run_with_capture(
        capture, api_key="dummy-key",
        gateway_url="https://gateway.ai.cloudflare.com/v1/acct123/agent-mesh/openrouter/chat/completions")
    assert result["story"] == _long_story()
    assert "(via AI Gateway)" in result["model"]
    url, headers = capture.calls[0]
    assert url == "https://gateway.ai.cloudflare.com/v1/acct123/agent-mesh/openrouter/chat/completions"
    assert "Authorization" not in headers


def test_direct_route_posts_to_openrouter_with_auth_header():
    capture = _Capture()
    result = _run_with_capture(capture, api_key="dummy-key")
    assert result["story"] == _long_story()
    assert "(via AI Gateway)" not in result["model"]
    url, headers = capture.calls[0]
    assert url == API_URL
    assert headers["Authorization"] == "Bearer dummy-key"
