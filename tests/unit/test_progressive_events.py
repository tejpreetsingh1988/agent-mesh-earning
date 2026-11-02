"""Progressive agent cards: each stream event carries its agent's
output, not just its name, so the frontend can render a card the
moment its agent finishes.

Covers mesh/orchestrator_async.py's enriched events: scout_done
carries the fact list, analyst_done the claim list,
critic_attempt the issue list, writer_done the story — each
with duration_ms — while the old count keys stay unchanged.
"""
import asyncio

from mesh.orchestrator_async import run_briefing_async


def _pack_dict():
    return {
        "ticker": "GOOGL", "company_name": "Alphabet Inc.",
        "quarter_label": "Q3 2026", "quarter_end": "2026-09-30",
        "report_date": "2026-10-28T00:00:00+00:00", "status": "REPORTED",
        "facts": [{"id": "rev", "metric": "total_revenue", "value": 127.6,
                   "unit": "USD_B", "period": "2026-09-30",
                   "source": {"url": "", "publisher": "SEC EDGAR",
                            "retrieved_at": "2026-10-28T00:00:00+00:00"}}],
        "transcript": {"status": "available", "source": "Motley Fool",
                       "url": "", "takeaways": [], "summary": "", "excerpt": ""},
    }


def _analysis_dict():
    return {"ticker": "GOOGL", "quarter_label": "Q3 2026",
            "verdict_draft": "draft",
            "claims": [{"text": "Revenue up", "value": 24.7,
                        "derivation": "YoY", "evidence_ids": ["rev"]}]}


def _briefing_dict():
    return {"ticker": "GOOGL", "quarter_label": "Q3 2026", "verdict": "v",
            "story": "Story text here.", "story_model": "test-model",
            "trace_id": "trace-test"}


def test_progressive_events_carry_content_and_durations():
    async def go():
        events = []

        async def scout(t):
            return _pack_dict()

        async def analyst(pack):
            return _analysis_dict()

        async def critic(pack, analysis):
            return {"verdict": "PASS", "issues": [], "rechecked_facts": []}

        async def writer(pack, analysis, trace_id):
            return _briefing_dict()

        await run_briefing_async(
            "GOOGL", scout, analyst, critic, writer, on_event=events.append)
        return events

    events = asyncio.run(go())
    by_name = {e["event"]: e for e in events}
    scout_done = by_name["scout_done"]
    assert scout_done["facts"] == 1
    assert len(scout_done["fact_list"]) == 1
    assert scout_done["fact_list"][0]["metric"] == "total_revenue"
    assert scout_done["company_name"] == "Alphabet Inc."
    assert scout_done["transcript_status"] == "available"
    assert isinstance(scout_done["duration_ms"], int)
    analyst_done = by_name["analyst_done"]
    assert analyst_done["claims"] == 1
    assert analyst_done["claim_list"][0]["text"] == "Revenue up"
    critic_attempt = by_name["critic_attempt"]
    assert critic_attempt["verdict"] == "PASS"
    assert critic_attempt["issue_list"] == []
    writer_done = by_name["writer_done"]
    assert writer_done["story"] == "Story text here."
    assert writer_done["story_model"] == "test-model"
