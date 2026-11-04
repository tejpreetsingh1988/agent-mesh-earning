"""error_event: structured final stream events for failed runs."""

from mesh.orchestrator import CriticFailed
from mesh.orchestrator_async import error_event


def test_critic_refusal_carries_verdict_and_issues():
    issues = [{"check": "staleness", "message": "revenue claim cites 2019 facts"}]
    ev = error_event(CriticFailed(issues))
    assert ev["event"] == "error"
    assert ev["verdict"] == "FAIL"
    assert ev["issues"] == issues
    assert ev["error"].startswith("Critic FAIL")


def test_other_failures_stay_plain():
    ev = error_event(ValueError("boom"))
    assert ev == {"event": "error", "error": "boom"}
    assert "verdict" not in ev
    assert "issues" not in ev
