"""Batch 31 — stream resume: run_briefing_async fast-forwards past
stages whose outputs are stored in resume_from.

A stage present in resume_from is skipped with NO agent call and
NO events for it, and its stored output feeds the next stage. A
stored critique is honoured only on PASS; a stored FAIL means the
Critic loop runs fresh. The Writer always runs (a completed
briefing is a "done" checkpoint, handled by the stream endpoint,
not by this function). No live APIs: the pack comes from the
Scout test fixture, the analysis from the real Analyst, the
Critic and Writer are fakes returning fixed dicts.
"""
import asyncio
import copy

from mesh.analyst import analyse
from mesh.orchestrator import CriticFailed
from mesh.orchestrator_async import run_briefing_async
from tests.unit.test_scout_analyst import _googl_pack


def _pack_data():
    return _googl_pack().model_dump(mode="json")


def _analysis_data():
    return analyse(_googl_pack()).model_dump(mode="json")


def _briefing_dict():
    return {"ticker": "GOOGL", "quarter_label": "Q3 2026",
            "verdict": "test", "story": "test story",
            "story_model": "fake", "trace_id": "trace-test"}


def _run(resume_from=None, critic_script=None):
    """Run the pipeline with counting fakes. critic_script is the
    list of verdicts the fake Critic returns in order (default:
    PASS on the first attempt). Returns (briefing, calls, events).
    """
    calls = {"scout": 0, "analyst": 0, "critic": 0, "writer": 0}
    events = []
    script = list(critic_script or ["PASS"])

    async def scout_fn(ticker):
        calls["scout"] += 1
        return _pack_data()

    async def analyst_fn(pack):
        calls["analyst"] += 1
        return _analysis_data()

    async def critic_fn(pack, analysis):
        calls["critic"] += 1
        verdict = script.pop(0) if script else "PASS"
        return {"verdict": verdict, "issues": []}

    async def writer_fn(pack, analysis, trace_id):
        calls["writer"] += 1
        return _briefing_dict()

    async def on_event(ev):
        events.append(ev)

    briefing = asyncio.run(run_briefing_async(
        "GOOGL", scout_fn, analyst_fn, critic_fn, writer_fn,
        on_event=on_event, resume_from=resume_from))
    return briefing, calls, events


def _kinds(events):
    return [e["event"] for e in events]


def test_fresh_run_calls_everything_in_order():
    briefing, calls, events = _run()
    assert briefing.ticker == "GOOGL"
    assert calls == {"scout": 1, "analyst": 1, "critic": 1, "writer": 1}
    assert _kinds(events) == ["scout_started", "scout_done", "analyst_done",
                              "critic_attempt", "writer_done"]


def test_resume_pack_only_skips_scout():
    _, calls, events = _run(resume_from={"pack": _pack_data()})
    assert calls["scout"] == 0
    assert calls["analyst"] == 1 and calls["critic"] == 1 and calls["writer"] == 1
    assert "scout_started" not in _kinds(events)
    assert "scout_done" not in _kinds(events)
    assert _kinds(events) == ["analyst_done", "critic_attempt", "writer_done"]


def test_resume_pack_and_analysis_skips_both():
    _, calls, events = _run(resume_from={"pack": _pack_data(),
                                         "analysis": _analysis_data()})
    assert calls["scout"] == 0 and calls["analyst"] == 0
    assert calls["critic"] == 1 and calls["writer"] == 1
    assert _kinds(events) == ["critic_attempt", "writer_done"]


def test_resume_pass_critique_skips_critic():
    _, calls, events = _run(resume_from={
        "pack": _pack_data(), "analysis": _analysis_data(),
        "critique": {"verdict": "PASS", "issues": []}})
    assert calls["scout"] == 0 and calls["analyst"] == 0 and calls["critic"] == 0
    assert calls["writer"] == 1
    assert _kinds(events) == ["writer_done"]


def test_resume_fail_critique_reruns_critic_loop():
    # Stored FAIL is ignored: attempt 1 FAILs again, the Analyst
    # re-runs (the one analyst call), attempt 2 PASSes, Writer runs.
    _, calls, events = _run(
        resume_from={"pack": _pack_data(), "analysis": _analysis_data(),
                     "critique": {"verdict": "FAIL", "issues": [{"severity": "fail"}]}},
        critic_script=["FAIL", "PASS"])
    assert calls["scout"] == 0
    assert calls["analyst"] == 1  # the retry re-run only, not the initial
    assert calls["critic"] == 2
    assert calls["writer"] == 1
    assert _kinds(events) == ["critic_attempt", "analyst_done",
                              "critic_attempt", "writer_done"]


def test_resume_critic_fail_twice_raises():
    try:
        _run(resume_from={"pack": _pack_data(), "analysis": _analysis_data()},
             critic_script=["FAIL", "FAIL"])
    except CriticFailed:
        pass
    else:
        raise AssertionError("expected CriticFailed after two FAILs")


def test_resume_not_reported_pack_raises_before_analyst():
    pack = _pack_data()
    pack["status"] = "NOT_REPORTED_YET"
    pack["missing"] = ["no filing"]
    try:
        _run(resume_from={"pack": pack})
    except ValueError as e:
        assert "NOT_REPORTED_YET" in str(e)
    else:
        raise AssertionError("expected ValueError for NOT_REPORTED_YET pack")


def test_resume_pack_object_is_not_mutated():
    # The stored pack dict is validated, never rewritten: a resume
    # must not corrupt the checkpoint for a second resume.
    pack = _pack_data()
    snapshot = copy.deepcopy(pack)
    _run(resume_from={"pack": pack})
    assert pack == snapshot
