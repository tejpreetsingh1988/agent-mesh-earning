"""Regression tests for the MSFT stale-facts briefing (Nov 2, 2026).

The live MSFT briefing labelled Q3 2026 carried revenue from
2009-2010 and a 230.1% operating margin (2026 operating income
divided by 2010 revenue). Three independent holes, each fixed
and each tested here:

1. Tag pick: edgar_facts picked the first tag with ANY rows, so
   MSFT's retired `Revenues` tag (rows ending 2010) beat the
   current contract-revenue tag. Now recency decides.
2. Analyst margin: it fell back to the latest operating income
   of ANY period when the latest revenue period had none. Now
   a margin needs a common period, or there is no margin claim.
3. Critic: pack-level staleness looked at the newest fact of
   ANY metric, so one current metric masked a 16-year-old one.
   Now each claim's own evidence must be within a year of the
   reported quarter, and the margin recomputation also needs a
   common period.
"""
import asyncio
from datetime import date, datetime, timezone

from mesh import async_tools
from mesh.analyst import analyse
from mesh.critic import critique
from mesh.critic_async import critique_async
from mesh.edgar_facts import get_quarterly_facts, pick_latest_tag
from mesh.schemas import Analysis, Claim, EvidencePack, Fact, SourceRef


def _src():
    return SourceRef(url="", publisher="SEC EDGAR",
                     retrieved_at=datetime.now(timezone.utc), excerpt="test")


def _fact(fid, metric, value, period):
    return Fact(id=fid, metric=metric, value=value, unit="USD_B",
                period=period, source=_src())


def _pack(facts, quarter_end=date(2026, 9, 30)):
    return EvidencePack(
        ticker="MSFT", company_name="MICROSOFT CORP",
        quarter_label="Q3 2026", quarter_end=quarter_end,
        report_date=datetime(2026, 10, 28, tzinfo=timezone.utc),
        status="REPORTED", facts=facts)


def _concept(rows):
    """rows: (start, end, val) -> EDGAR companyconcept payload."""
    return {"units": {"USD": [
        {"form": "10-Q", "start": s, "end": e, "val": v,
         "filed": e, "accn": f"accn-{e}"} for s, e, v in rows]}}


# --- 1. Tag pick -------------------------------------------------

def test_pick_latest_tag_prefers_recency_over_priority():
    old = [{"period_end": "2010-12-31"}, {"period_end": "2009-12-31"}]
    new = [{"period_end": "2026-09-30"}, {"period_end": "2025-09-30"}]
    tag, rows = pick_latest_tag([("Revenues", old),
                                 ("RevenueFromContractWithCustomerExcludingAssessedTax", new)])
    assert tag == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert rows[0]["period_end"] == "2026-09-30"


def test_pick_latest_tag_tie_keeps_priority_and_empty_is_none():
    rows = [{"period_end": "2026-09-30"}]
    tag, _ = pick_latest_tag([("A", rows), ("B", rows)])
    assert tag == "A"
    assert pick_latest_tag([("A", []), ("B", [])]) is None


def test_get_quarterly_facts_msft_revenue_tag():
    payloads = {
        "Revenues": _concept([
            ("2009-10-01", "2009-12-31", 19.022e9),
            ("2010-10-01", "2010-12-31", 19.953e9)]),
        "RevenueFromContractWithCustomerExcludingAssessedTax": _concept([
            ("2025-07-01", "2025-09-30", 70.0e9),
            ("2026-07-01", "2026-09-30", 77.0e9)]),
    }

    def fake_fetch(cik, tag):
        if tag in payloads:
            return payloads[tag]
        return {"units": {}}

    out = get_quarterly_facts(789019, fetch=fake_fetch)
    assert out["total_revenue"]["tag"] == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert out["total_revenue"]["rows"][0]["period_end"] == "2026-09-30"


def test_async_get_quarterly_facts_msft_revenue_tag(monkeypatch):
    payloads = {
        "Revenues": _concept([
            ("2009-10-01", "2009-12-31", 19.022e9),
            ("2010-10-01", "2010-12-31", 19.953e9)]),
        "RevenueFromContractWithCustomerExcludingAssessedTax": _concept([
            ("2025-07-01", "2025-09-30", 70.0e9),
            ("2026-07-01", "2026-09-30", 77.0e9)]),
    }

    async def fake_fetch(cik, tag):
        return payloads.get(tag, {"units": {}})

    monkeypatch.setattr(async_tools, "_fetch_concept", fake_fetch)
    out = asyncio.run(async_tools.async_get_quarterly_facts(789019))
    assert out["total_revenue"]["tag"] == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert out["total_revenue"]["rows"][0]["period_end"] == "2026-09-30"


# --- 2. Analyst margin -------------------------------------------

def test_analyst_margin_needs_common_period():
    pack = _pack([
        _fact("r10", "total_revenue", 20.0, "2010-12-31"),
        _fact("r09", "total_revenue", 19.0, "2009-12-31"),
        _fact("o26", "operating_income", 45.9, "2026-09-30"),
        _fact("o25", "operating_income", 38.0, "2025-09-30"),
    ])
    analysis = analyse(pack)
    assert not [c for c in analysis.claims if c.text.startswith("Operating margin")]
    assert any("no common filed period" in r for r in analysis.risks_and_watch)


def test_analyst_margin_with_common_period():
    pack = _pack([
        _fact("r26", "total_revenue", 100.0, "2026-09-30"),
        _fact("r25", "total_revenue", 90.0, "2025-09-30"),
        _fact("o26", "operating_income", 30.0, "2026-09-30"),
        _fact("o25", "operating_income", 25.0, "2025-09-30"),
    ])
    analysis = analyse(pack)
    margin = [c for c in analysis.claims if c.text.startswith("Operating margin")]
    assert len(margin) == 1
    assert abs(margin[0].value - 30.0) < 0.01


# --- 3. Critic ----------------------------------------------------

def _claim(text, value, ids):
    return Claim(text=text, value=value, derivation="test", evidence_ids=ids)


def test_critic_fails_stale_claim():
    pack = _pack([
        _fact("r10", "total_revenue", 20.0, "2010-12-31"),
        _fact("r09", "total_revenue", 19.0, "2009-12-31"),
        _fact("o26", "operating_income", 45.9, "2026-09-30"),
        _fact("o25", "operating_income", 38.0, "2025-09-30"),
    ])
    analysis = Analysis(
        ticker="MSFT", quarter_label="Q3 2026", verdict_draft="test",
        claims=[
            _claim("Revenue YoY growth (2009-12-31 -> 2010-12-31): +4.9%", 4.9, ["r10", "r09"]),
            _claim("Operating income YoY growth (2025-09-30 -> 2026-09-30): +21.0%", 21.0, ["o26", "o25"]),
        ])
    result = critique(pack, analysis)
    assert result.verdict == "FAIL"
    assert any(i["check"] == "staleness" for i in result.issues)


def test_critic_passes_fresh_pack_and_async_mirror():
    pack = _pack([
        _fact("r26", "total_revenue", 100.0, "2026-09-30"),
        _fact("r25", "total_revenue", 90.0, "2025-09-30"),
        _fact("o26", "operating_income", 30.0, "2026-09-30"),
        _fact("o25", "operating_income", 25.0, "2025-09-30"),
    ])
    analysis = Analysis(
        ticker="MSFT", quarter_label="Q3 2026", verdict_draft="test",
        claims=[
            _claim("Revenue YoY growth (2025-09-30 -> 2026-09-30): +11.1%", 11.1, ["r26", "r25"]),
            _claim("Operating income YoY growth (2025-09-30 -> 2026-09-30): +20.0%", 20.0, ["o26", "o25"]),
            _claim("Operating margin (2026-09-30): 30.0%", 30.0, ["o26", "r26"]),
        ])
    assert critique(pack, analysis).verdict == "PASS"
    assert asyncio.run(critique_async(pack, analysis, mcp_call=None)).verdict == "PASS"


def test_critic_margin_without_common_period_fails_claim_not_omission():
    pack = _pack([
        _fact("r10", "total_revenue", 20.0, "2010-12-31"),
        _fact("o26", "operating_income", 45.9, "2026-09-30"),
    ])
    analysis = Analysis(
        ticker="MSFT", quarter_label="Q3 2026", verdict_draft="test",
        claims=[_claim("Operating margin (2010-12-31): 230.1%", 230.1, ["o26", "r10"])])
    result = critique(pack, analysis)
    assert result.verdict == "FAIL"
    assert any(i["check"] == "margin" for i in result.issues)
    # No margin claim at all must NOT fail omission when there is
    # no common period: a correct Analysis omits it.
    empty = Analysis(ticker="MSFT", quarter_label="Q3 2026",
                     verdict_draft="test", claims=[])
    assert not any(i["check"] == "omission"
                   for i in critique(pack, empty).issues)
