"""Derived-Q4 fiscal-year pairing (Nov 4, 2026 fix).

derive_q4_rows used to key the FY and 9-month YTD rows by the
calendar year of their end date. For fiscal calendars that pairs
the wrong rows: NVDA's FY2025 10-K ends Jan 2025 while FY2026's
9-month YTD ends Oct 2025 — same calendar year, different fiscal
years — and FY − YTD came out as −$17.3B of "revenue", a negative
fact that shipped in live packs (Nov 4, 2026) while the real Q4
FY2026 row (Jan 2026) never appeared. The pairing key is now the
row's `fy` field (falling back to end-date year for rows that
lack one), with an `fp` guard (YTD must be Q3, FY must be FY).
"""

from mesh.edgar_facts import derive_q4_rows


def _row(form, start, end, val, fy=None, fp=None):
    r = {"form": form, "start": start, "end": end, "val": val,
         "filed": "2026-01-01", "accn": "0000000000-00-000000"}
    if fy is not None:
        r["fy"] = fy
    if fp is not None:
        r["fp"] = fp
    return r


def _concept(rows):
    return {"units": {"USD": rows}}


def test_nvda_fiscal_years_pair_correctly():
    # Real FY2025 pair: FY revenue $130,497M, 9M YTD $91,166M →
    # Q4 FY2025 $39,331M (NVDA's actual Q4 FY2025 revenue $39.3B).
    # Synthetic FY2026 pair: FY $215,000M, 9M YTD $147,811M.
    rows = [
        _row("10-K", "2025-01-27", "2026-01-25", 215000e6, 2026, "FY"),
        _row("10-Q", "2025-01-27", "2025-10-26", 147811e6, 2026, "Q3"),
        _row("10-K", "2024-01-29", "2025-01-26", 130497e6, 2025, "FY"),
        _row("10-Q", "2024-01-29", "2024-10-27", 91166e6, 2025, "Q3"),
    ]
    out = derive_q4_rows(_concept(rows), "total_revenue")
    by_end = {r["period_end"]: r for r in out}
    assert set(by_end) == {"2026-01-25", "2025-01-26"}
    assert abs(by_end["2026-01-25"]["value"] - 67189e6) < 1
    assert abs(by_end["2025-01-26"]["value"] - 39331e6) < 1
    assert all(r["value"] > 0 for r in out)
    assert all(r.get("derived") for r in out)
    assert by_end["2026-01-25"]["form"] == "10-K (derived Q4)"


def test_calendar_company_still_derives():
    # December year-end: fy == end-date year, so the old and new
    # keyings agree — this is the regression guard.
    rows = [
        _row("10-K", "2025-07-01", "2026-06-30", 300000e6, 2026, "FY"),
        _row("10-Q", "2025-07-01", "2026-03-31", 220000e6, 2026, "Q3"),
    ]
    out = derive_q4_rows(_concept(rows), "total_revenue")
    assert len(out) == 1
    assert out[0]["period_end"] == "2026-06-30"
    assert abs(out[0]["value"] - 80000e6) < 1


def test_rows_without_fy_fall_back_to_end_year():
    rows = [
        _row("10-K", "2025-07-01", "2026-06-30", 300000e6),
        _row("10-Q", "2025-07-01", "2026-03-31", 220000e6),
    ]
    out = derive_q4_rows(_concept(rows), "total_revenue")
    assert len(out) == 1
    assert abs(out[0]["value"] - 80000e6) < 1


def test_non_q3_ytd_row_ignored():
    # A 10-Q with a 9-month duration whose fp is not Q3 is not a
    # 9-month YTD row — never pair it against the FY.
    rows = [
        _row("10-K", "2025-01-27", "2026-01-25", 215000e6, 2026, "FY"),
        _row("10-Q", "2025-01-27", "2025-10-26", 147811e6, 2026, "Q2"),
    ]
    assert derive_q4_rows(_concept(rows), "total_revenue") == []
