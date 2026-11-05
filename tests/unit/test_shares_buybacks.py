"""Batch 25: shares outstanding (DEI cover tag) + buybacks.

Shares outstanding comes from the DEI cover-page tag
EntityCommonStockSharesOutstanding — instants whose
period is the cover date, about a month after the
quarter end. Buybacks come from the two
repurchase-payment tags (current and older
convention), YTD-differenced like CapEx.
"""
import asyncio

from mesh import async_tools
from mesh.analyst import analyse
from mesh.edgar_facts import get_quarterly_facts, parse_instant_rows
from mesh.schemas import EvidencePack


def _row(start, end, val, form="10-Q", fp="Q1", fy="2026", filed="2026-10-28"):
    return {"start": start, "end": end, "val": val, "form": form,
            "fp": fp, "fy": fy, "filed": filed, "accn": "0000000000-26-000001"}


def _cover(end, val, fp="Q1", fy="2026", filed="2026-10-28"):
    return {"end": end, "val": val, "form": "10-Q",
            "fp": fp, "fy": fy, "filed": filed, "accn": "0000000000-26-000001"}


def test_instant_dedupe_is_per_fiscal_quarter():
    # Same quarter re-filed by an amendment: two cover
    # dates, one quarter. Latest filed wins, one row.
    concept = {"units": {"shares": [
        _cover("2025-10-23", 7432377655, filed="2025-10-28"),
        _cover("2025-11-10", 7431000000, filed="2025-11-15"),
        _cover("2026-01-22", 7425629076, fp="Q2", filed="2026-01-27"),
    ]}}
    rows = parse_instant_rows(concept, "shares_outstanding")
    assert [r["period_end"] for r in rows] == ["2026-01-22", "2025-11-10"]
    assert rows[1]["value"] == 7431000000


def test_quarterly_facts_buybacks_and_shares():
    def fake_fetch(cik, tag):
        if tag == "PaymentsForRepurchaseOfCommonStock":
            return {"units": {"USD": [
                _row("2025-01-01", "2025-03-31", 4000000000, fp="Q1", fy="2025"),
                _row("2025-01-01", "2025-06-30", 9000000000, fp="Q2", fy="2025"),
                _row("2025-01-01", "2025-09-30", 15000000000, fp="Q3", fy="2025"),
            ]}}
        if tag == "dei:EntityCommonStockSharesOutstanding":
            return {"units": {"shares": [
                _cover("2025-10-23", 7432377655, fp="Q1", fy="2026"),
                _cover("2026-01-22", 7425629076, fp="Q2", fy="2026"),
            ]}}
        return {"units": {}}

    out = get_quarterly_facts(789019, fetch=fake_fetch)
    bb = {r["period_end"]: r for r in out["buybacks"]["rows"]}
    assert bb["2025-03-31"]["value"] == 4000000000
    assert bb["2025-06-30"]["value"] == 5000000000
    assert bb["2025-09-30"]["value"] == 6000000000
    assert out["shares_outstanding"]["tag"] == "dei:EntityCommonStockSharesOutstanding"
    sh = {r["period_end"]: r for r in out["shares_outstanding"]["rows"]}
    assert sh["2025-10-23"]["value"] == 7432377655
    assert sh["2026-01-22"]["value"] == 7425629076


def _src():
    return {"url": "https://www.sec.gov/Archives/test", "publisher": "SEC EDGAR",
            "retrieved_at": "2026-10-28T16:00:00Z"}


def _fact(fid, metric, value, period, unit="USD_B"):
    return {"id": fid, "metric": metric, "value": value, "unit": unit,
            "period": period, "source": _src()}


def test_analyst_claims_for_buybacks_and_shares():
    pack = EvidencePack(
        ticker="MSFT", company_name="Microsoft Corporation", quarter_label="Q3 2026",
        quarter_end="2026-03-31", report_date="2026-04-29T16:00:00Z", status="REPORTED",
        facts=[
            _fact("bb_2025", "buybacks", 4.0, "2025-03-31"),
            _fact("bb_2026", "buybacks", 6.0, "2026-03-31"),
            _fact("sh_2025", "shares_outstanding", 7.43, "2025-10-23", "shares_B"),
            _fact("sh_2026", "shares_outstanding", 7.42, "2026-10-22", "shares_B"),
        ],
    )
    analysis = analyse(pack)
    texts = [c.text for c in analysis.claims]
    assert any("Buybacks YoY growth" in t and "+50.0%" in t for t in texts)
    assert any("Shares outstanding YoY growth" in t and "-0.1%" in t
               and "7.43B shares" in t for t in texts)


def test_async_path_yields_derived_metrics_and_shares(monkeypatch):
    # The cloud path must not drift from the sync path:
    # same derivations, same DEI tag, via the async mirror.
    payloads = {
        "OperatingIncomeLoss": {"units": {"USD": [
            _row("2025-07-01", "2025-09-30", 30000000000, fp="Q1"),
        ]}},
        "Depreciation": {"units": {"USD": [
            _row("2025-07-01", "2025-09-30", 7100000000, fp="Q1"),
        ]}},
        "PaymentsForRepurchaseOfCommonStock": {"units": {"USD": [
            _row("2025-07-01", "2025-09-30", 4000000000, fp="Q1"),
        ]}},
        "dei:EntityCommonStockSharesOutstanding": {"units": {"shares": [
            _cover("2025-10-23", 7432377655, fp="Q1", fy="2026"),
        ]}},
    }

    async def fake_fetch(cik, tag):
        return payloads.get(tag, {"units": {}})

    monkeypatch.setattr(async_tools, "_fetch_concept", fake_fetch)
    out = asyncio.run(async_tools.async_get_quarterly_facts(789019))
    assert out["ebitda"]["rows"][0]["value"] == 30000000000 + 7100000000
    assert out["buybacks"]["rows"][0]["value"] == 4000000000
    assert out["shares_outstanding"]["rows"][0]["value"] == 7432377655
