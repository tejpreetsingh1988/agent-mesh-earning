"""Batch 28 (flipped Nov 4, 2026): Nasdaq JSON parsing, reaction
window selection, and the Analyst/Critic "next row after report
date" rule (weekends and holidays skipped by construction).

Stooq was the original source, but it serves nothing to
automated clients — VM curl times out, a text fetch fails, and
a real browser tab renders blank with no CSV — so the fetcher
moved to Nasdaq historical JSON. The parser, window, payload,
Analyst and Critic code are source-agnostic and unchanged; only
the fetcher and the source label moved. No live Nasdaq calls
here: the live shape (MM/DD/YYYY dates, '$' closes, comma
volumes, newest first) comes from a VM curl probe Nov 4, 2026,
and live verification rides the post-deploy briefing checks.
"""
import asyncio
import json
from datetime import date, datetime

from mesh.analyst import analyse
from mesh.async_tools import async_get_price_reaction
from mesh.critic import critique
from mesh.market import parse_nasdaq_closes, reaction_payload
from mesh.schemas import Analysis, EvidencePack

NASDAQ_NEWEST_FIRST = {
    "data": {"tradesTable": {"rows": [
        {"date": "11/02/2026", "close": "$303.50", "volume": "1,000,000", "open": "$300.00"},
        {"date": "10/30/2026", "close": "$292.00", "volume": "900,000", "open": "$290.00"},
        {"date": "10/29/2026", "close": "$282.00", "volume": "800,000", "open": "$280.00"},
        {"date": "10/28/2026", "close": "$272.00", "volume": "700,000", "open": "$270.00"},
        {"date": "10/27/2026", "close": "$262.00", "volume": "600,000", "open": "$260.00"},
        {"date": "bad-date", "close": "$1.00", "volume": "1", "open": "$1.00"},
        {"date": "10/26/2026", "close": "n/a", "volume": "500,000", "open": "$250.00"},
        {"date": "10/23/2026", "close": "$252.00", "volume": "500,000", "open": "$250.00"},
    ]}}
}


def test_parse_nasdaq_closes_sorts_ascending_and_skips_bad_rows():
    rows = parse_nasdaq_closes(NASDAQ_NEWEST_FIRST)
    assert [r["date"] for r in rows] == [
        "2026-10-23", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30", "2026-11-02"]
    assert rows[0]["close"] == 252.0 and rows[-1]["close"] == 303.5
    assert rows[0]["volume"] == 500000 and rows[0]["open"] == 250.0
    assert parse_nasdaq_closes({}) == []
    assert parse_nasdaq_closes({"data": {"tradesTable": {"rows": []}}}) == []


def test_reaction_payload_window_trims_to_context():
    closes = [{"date": f"2026-10-{d:02d}", "close": 100.0 + d} for d in range(1, 31)]
    payload = reaction_payload("GOOGL", "2026-10-15", closes)
    dates = [c["date"] for c in payload["closes"]]
    # 5 before base (10-15) through 5 after reaction (10-16).
    assert dates[0] == "2026-10-10" and dates[-1] == "2026-10-21"
    assert payload["source"] == "Nasdaq (free)"
    assert "unadjusted" in payload["window"] and "after-hours" in payload["window"]


def _pack_with_closes(closes, report_date):
    return EvidencePack(
        ticker="GOOGL", company_name="Alphabet Inc.", quarter_label="Q3 2026",
        quarter_end=date(2026, 9, 30), report_date=datetime.fromisoformat(report_date),
        status="REPORTED", facts=[], consensus={"status": "unavailable"},
        price_reaction={"closes": closes})


def _analysis_for(pack):
    return analyse(pack)


def test_analyst_weekend_report_uses_friday_and_monday():
    # Reported Saturday 2026-10-31: base = Friday 10-30, reaction = Monday 11-02.
    pack = _pack_with_closes([
        {"date": "2026-10-28", "close": 272.0},
        {"date": "2026-10-29", "close": 282.0},
        {"date": "2026-10-30", "close": 292.0},
        {"date": "2026-11-02", "close": 303.5},
    ], "2026-10-31T16:00:00")
    a = _analysis_for(pack)
    pr = next(b for b in a.beat_miss if b["metric"] == "price_reaction")
    assert pr["window"] == "2026-10-30 -> 2026-11-02"
    assert abs(pr["diff_pct"] - round((303.5 / 292.0 - 1) * 100, 2)) < 0.01
    claim = next(c for c in a.claims if "Regular-session close change" in c.text)
    assert "2026-10-30 -> 2026-11-02" in claim.text
    assert "NOT an after-hours move" in claim.derivation


def test_analyst_no_reaction_yet_notes_it_without_claim():
    pack = _pack_with_closes([
        {"date": "2026-10-28", "close": 272.0},
        {"date": "2026-10-29", "close": 282.0},
    ], "2026-10-29T16:00:00")
    a = _analysis_for(pack)
    assert not any(b.get("metric") == "price_reaction" for b in a.beat_miss)
    assert any("No trading-day close after the report date yet" in r for r in a.risks_and_watch)


def test_critic_recomputes_weekend_rule_and_catches_tampering():
    pack = _pack_with_closes([
        {"date": "2026-10-30", "close": 292.0},
        {"date": "2026-11-02", "close": 303.5},
    ], "2026-10-31T16:00:00")
    a = _analysis_for(pack)
    assert critique(pack, a).verdict == "PASS"
    tampered = Analysis.model_validate({**a.model_dump(), "beat_miss": [
        {**b, "diff_pct": 99.9} if b.get("metric") == "price_reaction" else b
        for b in a.beat_miss]})
    bad = critique(pack, tampered)
    assert bad.verdict == "FAIL"
    assert any("Price reaction" in i.get("message", "") for i in bad.issues)


def test_sync_price_reaction_parses_nasdaq_json(monkeypatch):
    # Fake the Nasdaq JSON fetch (same shape as the live probe).
    import urllib.request

    from mesh import market

    payload = {"data": {"tradesTable": {"rows": [
        {"date": "10/29/2026", "close": "$283.82", "volume": "139,738,300", "open": "$286.875"},
        {"date": "10/28/2026", "close": "$324.89", "volume": "63,109,030", "open": "$323.765"},
        {"date": "10/27/2026", "close": "$320.58", "volume": "28,633,060", "open": "$317.00"},
    ]}}}

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps(payload).encode()

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: FakeResp())
    r = market.get_price_reaction("GOOGL", report_date="2026-10-28")
    assert r["source"] == "Nasdaq (free)"
    dates = [c["date"] for c in r["closes"]]
    assert "2026-10-28" in dates and "2026-10-29" in dates
    assert r["closes"][0]["close"] == 320.58


def test_async_price_reaction_parses_nasdaq_json(monkeypatch):
    # Fake worker_http.fetch_json inside async_tools (the Worker path).
    import mesh.async_tools as at

    payload = {"data": {"tradesTable": {"rows": [
        {"date": "10/29/2026", "close": "$283.82", "volume": "139,738,300", "open": "$286.875"},
        {"date": "10/28/2026", "close": "$324.89", "volume": "63,109,030", "open": "$323.765"},
    ]}}}

    async def fake_fetch_json(url, headers=None):
        assert "api.nasdaq.com" in url and "GOOGL" in url
        return payload

    monkeypatch.setattr(at, "fetch_json", fake_fetch_json)
    r = asyncio.run(async_get_price_reaction("GOOGL", report_date="2026-10-28"))
    assert r["source"] == "Nasdaq (free)"
    assert [c["date"] for c in r["closes"]] == ["2026-10-28", "2026-10-29"]
