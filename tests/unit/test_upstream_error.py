"""Batch 61: a SEC 429 must not be labelled NOT_REPORTED_YET.

The Nov 12 MSFT live run failed on an SEC rate limit
("HTTP 429 for https://data.sec.gov/submissions/CIK0000789019.json")
and the app told the user MSFT had not reported yet — the wrong
story, with no retry offered. The Scout now returns status
UPSTREAM_ERROR for rate-limit / transient transport failures
(sync + async), the orchestrator raises with the pack's own
status, and error_event carries that status so the frontend can
offer a retry.
"""
import asyncio

import pytest

from mesh.orchestrator import run_briefing
from mesh.orchestrator_async import error_event
from mesh.scout import collect_evidence
from mesh.scout_async import collect_evidence_async

_429 = "HTTP 429 for https://data.sec.gov/submissions/CIK0000789019.json"


def _fake_429(server, tool, args=None):
    if (server, tool) == ("filings", "get_company_facts"):
        return {"ticker": "MSFT", "company_name": "Microsoft Corporation"}
    if (server, tool) == ("filings", "get_latest_earnings_filing"):
        raise RuntimeError(_429)
    raise AssertionError(f"unexpected tool call: {server}/{tool}")


def _fake_boom(server, tool, args=None):
    if (server, tool) == ("filings", "get_company_facts"):
        return {"ticker": "MSFT", "company_name": "Microsoft Corporation"}
    if (server, tool) == ("filings", "get_latest_earnings_filing"):
        raise RuntimeError("boom")
    raise AssertionError(f"unexpected tool call: {server}/{tool}")


async def _async_fake_429(server, tool, args=None):
    return _fake_429(server, tool, args)


async def _async_fake_boom(server, tool, args=None):
    return _fake_boom(server, tool, args)


def test_sync_scout_429_is_upstream_error():
    pack = collect_evidence("MSFT", _fake_429)
    assert pack.status == "UPSTREAM_ERROR"
    assert any("429" in m for m in pack.missing)
    assert pack.facts == []


def test_sync_scout_plain_failure_stays_not_reported():
    pack = collect_evidence("MSFT", _fake_boom)
    assert pack.status == "NOT_REPORTED_YET"


def test_async_scout_429_is_upstream_error():
    pack = asyncio.run(collect_evidence_async("MSFT", _async_fake_429))
    assert pack.status == "UPSTREAM_ERROR"
    assert any("429" in m for m in pack.missing)


def test_async_scout_plain_failure_stays_not_reported():
    pack = asyncio.run(collect_evidence_async("MSFT", _async_fake_boom))
    assert pack.status == "NOT_REPORTED_YET"


def test_orchestrator_raises_with_pack_status():
    pack = collect_evidence("MSFT", _fake_429)
    with pytest.raises(ValueError) as exc:
        run_briefing("MSFT", lambda t: pack.model_dump(mode="json"),
                     lambda p: {}, lambda p, a: {})
    assert str(exc.value).startswith("UPSTREAM_ERROR for MSFT:")


def test_error_event_carries_status():
    ev = error_event(ValueError(f"UPSTREAM_ERROR for MSFT: [{_429!r}]"))
    assert ev["event"] == "error"
    assert ev["status"] == "UPSTREAM_ERROR"
    ev2 = error_event(ValueError("NOT_REPORTED_YET for MSFT: []"))
    assert ev2["status"] == "NOT_REPORTED_YET"
    ev3 = error_event(ValueError("boom"))
    assert "status" not in ev3
