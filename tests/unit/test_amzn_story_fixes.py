"""AMZN story fixes (Nov 2, 2026).

1. The deterministic fallback printed tool-error notes (a missing
   yfinance module, a failed fetch) inside its "What to watch"
   paragraph, so the story read like an error log. Those notes
   belong only under Data notes; the story filters them now.
2. The story validator rejected "$1 trillion" — the Nemotron
   draft's echo of the call's own "1 trillion dollars" line —
   because the money pattern did not know the word "trillion"
   on either side. It does now, on both sides, so a transcript-
   backed trillion passes and an invented one still fails.
"""
from datetime import date, datetime, timezone

from mesh.llm import deterministic_story, validate_story
from mesh.schemas import Analysis, EvidencePack

_TOOL_NOTES = [
    "get_quarterly_history failed: No module named 'yfinance'",
    "get_price_reaction failed: No module named 'yfinance'",
]


def _pack(transcript=None):
    return EvidencePack(
        ticker="AMZN", company_name="Amazon.com, Inc.",
        quarter_label="Q3 2026", quarter_end=date(2026, 9, 30),
        report_date=datetime(2026, 10, 30, tzinfo=timezone.utc),
        status="REPORTED", transcript=transcript or {})


def _analysis(risks):
    return Analysis(ticker="AMZN", quarter_label="Q3 2026",
                    verdict_draft="Revenue up 12.1% YoY.",
                    risks_and_watch=risks)


def test_deterministic_story_filters_tool_notes_but_keeps_real_risks():
    story = deterministic_story(
        _pack(), _analysis(_TOOL_NOTES + ["Watch for AWS margin pressure"]))
    assert "No module named" not in story
    assert "yfinance" not in story
    assert "What to watch: Watch for AWS margin pressure." in story


def test_deterministic_story_drops_watch_paragraph_when_only_tool_notes():
    story = deterministic_story(_pack(), _analysis(_TOOL_NOTES))
    assert "What to watch" not in story
    assert "No module named" not in story


def _trillion_story(figure: str) -> str:
    return "\n\n".join([
        "The quarter was defined by strength in the core business, with revenue growth "
        "carrying the headline and margins holding firm as scale did its work across the segments.",
        f"Management pointed to a long runway ahead, describing a path toward reaching {figure} "
        "in annual revenue as workloads continue to shift and new capacity comes online.",
        "The operating story and the earnings story pulled in different directions this quarter, "
        "and the gap between them is the thing to understand before judging the result on any single line.",
        "What comes next depends on whether demand holds at the pace management described, "
        "and whether the investment cycle converts into durable growth rather than a short burst of spending.",
    ])


def _trillion_pack():
    return _pack(transcript={
        "status": "available",
        "takeaways": [],
        "summary": "The company is on a path toward reaching 1 trillion dollars "
                   "in annual revenue for both its AWS and stores businesses.",
        "excerpt": "",
    })


def test_validator_accepts_transcript_backed_trillion():
    ok, reason = validate_story(
        _trillion_story("$1 trillion"), _trillion_pack(), _analysis([]))
    assert ok, reason


def test_validator_still_rejects_invented_trillion():
    ok, reason = validate_story(
        _trillion_story("$5 trillion"), _trillion_pack(), _analysis([]))
    assert not ok
    assert "$5 trillion" in reason
