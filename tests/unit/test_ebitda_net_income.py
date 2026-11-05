"""Batch 21: net income + derived EBITDA growth.

Net income comes from the NetIncomeLoss XBRL tag, same
path as revenue. EBITDA has no GAAP tag, so it is
derived: operating income + depreciation & amortization
per period. D&A itself comes two ways — parsed discrete
quarterly rows where the filer reports them, and
YTD-difference rows where the filer reports cash-flow
D&A only year-to-date (see derive_discrete_ytd_rows).
"""
from mesh.analyst import analyse
from mesh.edgar_facts import derive_discrete_ytd_rows, get_quarterly_facts
from mesh.schemas import EvidencePack


def _row(start, end, val, form="10-Q", fp="Q1", fy="2026", filed="2026-10-28"):
    return {"start": start, "end": end, "val": val, "form": form,
            "fp": fp, "fy": fy, "filed": filed, "accn": "0000000000-26-000001"}


def _da_payload():
    # MSFT-shaped: Q1 discrete (= YTD), Q2/Q3 both a YTD row
    # and a discrete row, so the difference must agree with
    # the discrete row and the parsed row must win the dedupe.
    return {"units": {"USD": [
        _row("2025-07-01", "2025-09-30", 7100000000, fp="Q1"),
        _row("2025-07-01", "2025-12-31", 15000000000, fp="Q2"),
        _row("2025-10-01", "2025-12-31", 7900000000, fp="Q2"),
        _row("2025-07-01", "2026-03-31", 24000000000, fp="Q3"),
        _row("2026-01-01", "2026-03-31", 9000000000, fp="Q3"),
    ]}}


def test_ytd_difference_matches_discrete_rows():
    rows = derive_discrete_ytd_rows(_da_payload(), "depreciation_amortization")
    by_end = {r["period_end"]: r for r in rows}
    assert by_end["2025-12-31"]["value"] == 7900000000
    assert by_end["2026-03-31"]["value"] == 9000000000
    assert all(r["derived"] is True for r in rows)
    assert "YTD" in by_end["2025-12-31"]["derivation"]


def test_ytd_gap_yields_no_row():
    payload = {"units": {"USD": [
        _row("2025-07-01", "2025-09-30", 7100000000, fp="Q1"),
        # Q2 missing entirely; Q3 must NOT difference against Q1.
        _row("2025-07-01", "2026-03-31", 24000000000, fp="Q3"),
    ]}}
    assert derive_discrete_ytd_rows(payload, "depreciation_amortization") == []


def test_ytd_negative_difference_skipped():
    payload = {"units": {"USD": [
        _row("2025-07-01", "2025-09-30", 7100000000, fp="Q1"),
        _row("2025-07-01", "2025-12-31", 6000000000, fp="Q2"),  # restatement artifact
    ]}}
    assert derive_discrete_ytd_rows(payload, "depreciation_amortization") == []


def test_ytd_fiscal_year_grouping():
    # NVDA-shaped fiscal year: fy 2027 quarters end Apr/Jul/Oct 2026.
    payload = {"units": {"USD": [
        _row("2026-01-26", "2026-04-26", 1000000000, fp="Q1", fy="2027"),
        _row("2026-01-26", "2026-07-26", 2500000000, fp="Q2", fy="2027"),
        _row("2026-01-26", "2026-10-25", 4200000000, fp="Q3", fy="2027"),
    ]}}
    rows = derive_discrete_ytd_rows(payload, "depreciation_amortization")
    by_end = {r["period_end"]: r for r in rows}
    assert by_end["2026-07-26"]["value"] == 1500000000
    assert by_end["2026-10-25"]["value"] == 1700000000


def _fake_fetch_factory():
    payloads = {
        "OperatingIncomeLoss": {"units": {"USD": [
            _row("2025-07-01", "2025-09-30", 30000000000, fp="Q1"),
            _row("2025-10-01", "2025-12-31", 32000000000, fp="Q2"),
            _row("2026-01-01", "2026-03-31", 34000000000, fp="Q3"),
        ]}},
        "DepreciationDepletionAndAmortization": {"units": {}},
        "Depreciation": _da_payload(),
        "NetIncomeLoss": {"units": {"USD": [
            _row("2025-07-01", "2025-09-30", 25000000000, fp="Q1"),
            _row("2025-10-01", "2025-12-31", 26000000000, fp="Q2"),
            _row("2026-01-01", "2026-03-31", 27000000000, fp="Q3"),
        ]}},
    }

    def fake_fetch(cik, tag):
        return payloads.get(tag, {"units": {}})

    return fake_fetch


def test_quarterly_facts_has_net_income_and_ebitda():
    out = get_quarterly_facts(789019, fetch=_fake_fetch_factory())
    assert "net_income" in out
    assert [r["period_end"] for r in out["net_income"]["rows"]] == [
        "2026-03-31", "2025-12-31", "2025-09-30"]
    assert "ebitda" in out
    by_end = {r["period_end"]: r for r in out["ebitda"]["rows"]}
    assert by_end["2025-09-30"]["value"] == 30000000000 + 7100000000
    assert by_end["2025-12-31"]["value"] == 32000000000 + 7900000000
    assert by_end["2026-03-31"]["value"] == 34000000000 + 9000000000
    assert all(r["derived"] is True for r in out["ebitda"]["rows"])
    assert "Operating income" in by_end["2025-09-30"]["derivation"]
    assert out["ebitda"]["tag"].startswith("derived")


def test_quarterly_facts_ytd_only_da_still_yields_ebitda():
    # DUK-style: D&A reported YTD-only, no discrete rows at all.
    # Q1 parses (90 days); Q2/Q3 must come from YTD differences.
    def fake_fetch(cik, tag):
        if tag == "OperatingIncomeLoss":
            return {"units": {"USD": [
                _row("2025-01-01", "2025-03-31", 1000000000, fp="Q1", fy="2025"),
                _row("2025-04-01", "2025-06-30", 1100000000, fp="Q2", fy="2025"),
                _row("2025-07-01", "2025-09-30", 1200000000, fp="Q3", fy="2025"),
            ]}}
        if tag == "DepreciationDepletionAndAmortization":
            return {"units": {"USD": [
                _row("2025-01-01", "2025-03-31", 500000000, fp="Q1", fy="2025"),
                _row("2025-01-01", "2025-06-30", 1100000000, fp="Q2", fy="2025"),
                _row("2025-01-01", "2025-09-30", 1800000000, fp="Q3", fy="2025"),
            ]}}
        return {"units": {}}

    out = get_quarterly_facts(1326160, fetch=fake_fetch)
    by_end = {r["period_end"]: r for r in out["ebitda"]["rows"]}
    assert by_end["2025-03-31"]["value"] == 1000000000 + 500000000
    assert by_end["2025-06-30"]["value"] == 1100000000 + 600000000
    assert by_end["2025-09-30"]["value"] == 1200000000 + 700000000


def test_quarterly_facts_ocf_and_fcf_from_ytd():
    # OCF and CapEx reported YTD-only: discrete quarters
    # come from differences, FCF from OCF minus CapEx.
    def fake_fetch(cik, tag):
        if tag == "NetCashProvidedByUsedInOperatingActivities":
            return {"units": {"USD": [
                _row("2025-01-01", "2025-03-31", 10000000000, fp="Q1", fy="2025"),
                _row("2025-01-01", "2025-06-30", 22000000000, fp="Q2", fy="2025"),
                _row("2025-01-01", "2025-09-30", 36000000000, fp="Q3", fy="2025"),
            ]}}
        if tag == "PaymentsToAcquirePropertyPlantAndEquipment":
            return {"units": {"USD": [
                _row("2025-01-01", "2025-03-31", 4000000000, fp="Q1", fy="2025"),
                _row("2025-01-01", "2025-06-30", 9000000000, fp="Q2", fy="2025"),
                _row("2025-01-01", "2025-09-30", 15000000000, fp="Q3", fy="2025"),
            ]}}
        return {"units": {}}

    out = get_quarterly_facts(789019, fetch=fake_fetch)
    ocf = {r["period_end"]: r for r in out["operating_cash_flow"]["rows"]}
    assert ocf["2025-06-30"]["value"] == 12000000000
    assert ocf["2025-09-30"]["value"] == 14000000000
    fcf = {r["period_end"]: r for r in out["free_cash_flow"]["rows"]}
    assert fcf["2025-03-31"]["value"] == 6000000000
    assert fcf["2025-06-30"]["value"] == 7000000000
    assert fcf["2025-09-30"]["value"] == 8000000000
    assert all(r["derived"] is True for r in fcf.values())


def _instant(end, val, form="10-Q", filed="2026-10-28"):
    return {"end": end, "val": val, "form": form,
            "filed": filed, "accn": "0000000000-26-000001"}


def test_quarterly_facts_cash_instant_and_combined():
    def fake_fetch(cik, tag):
        if tag == "CashAndCashEquivalentsAtCarryingValue":
            return {"units": {"USD": [
                _instant("2025-09-30", 50000000000),
                _instant("2025-12-31", 55000000000),
                _instant("2026-03-31", 60000000000),
            ]}}
        if tag == "ShortTermInvestments":
            return {"units": {"USD": [
                _instant("2025-09-30", 30000000000),
                _instant("2025-12-31", 32000000000),
                _instant("2026-03-31", 35000000000),
            ]}}
        return {"units": {}}

    out = get_quarterly_facts(789019, fetch=fake_fetch)
    combined = {r["period_end"]: r for r in out["cash_and_st_investments"]["rows"]}
    assert combined["2025-09-30"]["value"] == 80000000000
    assert combined["2025-12-31"]["value"] == 87000000000
    assert combined["2026-03-31"]["value"] == 95000000000
    assert all(r["derived"] is True for r in combined.values())
    # The components stay in the pack too, for the derivation trail.
    assert "cash_and_equivalents" in out
    assert "short_term_investments" in out


def test_quarterly_facts_combined_cash_requires_both():
    def fake_fetch(cik, tag):
        if tag == "CashAndCashEquivalentsAtCarryingValue":
            return {"units": {"USD": [_instant("2025-09-30", 50000000000)]}}
        return {"units": {}}

    out = get_quarterly_facts(789019, fetch=fake_fetch)
    assert "cash_and_st_investments" not in out


def _src():
    return {"url": "https://www.sec.gov/Archives/test", "publisher": "SEC EDGAR",
            "retrieved_at": "2026-10-28T16:00:00Z"}


def _fact(fid, metric, value, period, unit="USD_B"):
    return {"id": fid, "metric": metric, "value": value, "unit": unit,
            "period": period, "source": _src()}


def test_analyst_growth_claims_for_net_income_and_ebitda():
    pack = EvidencePack(
        ticker="MSFT", company_name="Microsoft Corporation", quarter_label="Q3 2026",
        quarter_end="2026-03-31", report_date="2026-04-29T16:00:00Z", status="REPORTED",
        facts=[
            _fact("ni_2025", "net_income", 25.0, "2025-03-31"),
            _fact("ni_2026", "net_income", 27.0, "2026-03-31"),
            _fact("eb_2025", "ebitda", 37.1, "2025-03-31"),
            _fact("eb_2026", "ebitda", 43.0, "2026-03-31"),
        ],
    )
    analysis = analyse(pack)
    texts = [c.text for c in analysis.claims]
    assert any("Net income YoY growth" in t and "+8.0%" in t for t in texts)
    assert any("EBITDA YoY growth" in t and "+15.9%" in t for t in texts)


def test_analyst_growth_claims_for_cash_flow_and_cash():
    pack = EvidencePack(
        ticker="MSFT", company_name="Microsoft Corporation", quarter_label="Q3 2026",
        quarter_end="2026-03-31", report_date="2026-04-29T16:00:00Z", status="REPORTED",
        facts=[
            _fact("ocf_2025", "operating_cash_flow", 40.0, "2025-03-31"),
            _fact("ocf_2026", "operating_cash_flow", 46.7, "2026-03-31"),
            _fact("fcf_2025", "free_cash_flow", 12.0, "2025-03-31"),
            _fact("fcf_2026", "free_cash_flow", 15.8, "2026-03-31"),
            _fact("cash_2025", "cash_and_st_investments", 80.0, "2025-03-31"),
            _fact("cash_2026", "cash_and_st_investments", 95.0, "2026-03-31"),
        ],
    )
    analysis = analyse(pack)
    texts = [c.text for c in analysis.claims]
    assert any("Operating cash flow YoY growth" in t and "+16.8%" in t for t in texts)
    assert any("Free cash flow YoY growth" in t and "+31.7%" in t for t in texts)
    assert any("Cash and short-term investments YoY growth" in t and "+18.8%" in t for t in texts)
