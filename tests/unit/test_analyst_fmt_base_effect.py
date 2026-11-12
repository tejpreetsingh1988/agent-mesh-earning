"""Batch 61b: Analyst money formatting + base-effect notes.

DUOL's saved briefing showed "$0.3B -> $0.3B" for +13.7% revenue
growth and "$0.0B -> $0.0B" for -31.2% operating income — sub-billion
values rounded to one decimal in billions carry nothing. And its
GAAP EPS YoY claim (-90.9%) was driven by a $5.95 base quarter
that was ~6.5x the typical quarterly EPS — a one-off base, not an
operating collapse — presented without any context.
"""
from mesh.analyst import _base_effect_note, _fmt, analyse
from mesh.schemas import EvidencePack


def _src():
    return {"url": "https://www.sec.gov/Archives/test", "publisher": "SEC EDGAR",
            "retrieved_at": "2026-10-28T16:00:00Z"}


def _fact(fid, metric, value, period, unit="USD_B"):
    return {"id": fid, "metric": metric, "value": value, "unit": unit,
            "period": period, "source": _src()}


def test_fmt_sub_billion_uses_millions():
    assert _fmt(0.3, "USD_B") == "$300M"
    assert _fmt(0.04, "USD_B") == "$40M"
    assert _fmt(0.004, "USD_B") == "$4M"
    assert _fmt(3.7, "USD_B") == "$3.7B"
    assert _fmt(127.577, "USD_B") == "$127.6B"


def test_growth_claims_use_millions_below_a_billion():
    pack = EvidencePack(
        ticker="DUOL", company_name="Duolingo, Inc.", quarter_label="Q3 2026",
        quarter_end="2026-09-30", report_date="2026-11-04T16:00:00Z", status="REPORTED",
        facts=[
            _fact("rev_2025", "total_revenue", 0.3, "2025-09-30"),
            _fact("rev_2026", "total_revenue", 0.34, "2026-09-30"),
            _fact("oi_2025", "operating_income", 0.04, "2025-09-30"),
            _fact("oi_2026", "operating_income", 0.028, "2026-09-30"),
        ],
    )
    texts = [c.text for c in analyse(pack).claims]
    assert any("Revenue YoY growth" in t and "$300M -> $340M" in t for t in texts)
    assert any("Operating income YoY growth" in t and "$40M -> $28M" in t for t in texts)
    assert not any("$0.0B" in t or "$0.3B" in t for t in texts)


def _duol_eps_pack():
    # DUOL GAAP EPS (USD) — the Q3 2025 base quarter ($5.95) is the
    # outlier; every other quarter sits in $0.31–$0.94.
    eps = [("2025-03-31", 0.72), ("2025-06-30", 0.91), ("2025-09-30", 5.95),
           ("2025-12-31", 0.66), ("2026-03-31", 0.31), ("2026-06-30", 0.94),
           ("2026-09-30", 0.54)]
    facts = [_fact(f"eps_{p}", "gaap_eps", v, p, unit="USD") for p, v in eps]
    return EvidencePack(
        ticker="DUOL", company_name="Duolingo, Inc.", quarter_label="Q3 2026",
        quarter_end="2026-09-30", report_date="2026-11-04T16:00:00Z", status="REPORTED",
        facts=facts)


def test_outlier_base_quarter_gets_base_effect_note():
    texts = [c.text for c in analyse(_duol_eps_pack()).claims]
    yoy = [t for t in texts if "GAAP EPS YoY growth" in t]
    assert len(yoy) == 1
    assert "-90.9%" in yoy[0]
    assert "base effect" in yoy[0]
    assert "6.5x" in yoy[0] or "8.3x" in yoy[0]


def test_normal_series_gets_no_note():
    pack = EvidencePack(
        ticker="MSFT", company_name="Microsoft Corporation", quarter_label="Q3 2026",
        quarter_end="2026-03-31", report_date="2026-04-29T16:00:00Z", status="REPORTED",
        facts=[
            _fact("rev_2024", "total_revenue", 24.0, "2024-03-31"),
            _fact("rev_2025a", "total_revenue", 25.0, "2025-03-31"),
            _fact("rev_2025b", "total_revenue", 26.0, "2025-06-30"),
            _fact("rev_2025c", "total_revenue", 25.5, "2025-09-30"),
            _fact("rev_2026", "total_revenue", 27.0, "2026-03-31"),
        ],
    )
    texts = [c.text for c in analyse(pack).claims]
    assert all("base effect" not in t for t in texts)


def test_base_effect_note_needs_a_large_move():
    # Same outlier base, but a small move must not be annotated.
    from mesh.analyst import _pct
    fs = [(None, type("F", (), {"value": v, "period": p, "unit": "USD"})())
          for p, v in [("2025-03-31", 0.72), ("2025-06-30", 0.91),
                       ("2025-09-30", 5.95), ("2026-09-30", 5.40)]]
    prev, cur = fs[2][1], fs[3][1]
    assert abs(_pct(cur.value, prev.value)) < 25
    assert _base_effect_note(fs, prev, cur) == ""
