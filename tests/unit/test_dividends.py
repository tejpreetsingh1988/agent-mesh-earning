"""Feature 14 — dividend card data leg (mesh/dividends.py).

Unit: future ex-date excluded from the sum and reported as the
next declared ex-date; yield arithmetic on fixture rows (the
MSFT live probe's real rows: 4 x $0.91 = $3.64); Cash-only
filtering; unparseable amount/date rows dropped; yield hides
when the close is missing but rows still show. The route and
the frontend card land in the follow-up batch.
"""
import asyncio
from datetime import date

from mesh import dividends as div


def _msft_rows():
    # Real Nasdaq rows for MSFT, probed live 2026-11-05.
    return [
        {"exOrEffDate": "11/19/2026", "type": "Cash", "amount": "$0.98",
         "declarationDate": "09/15/2026", "recordDate": "11/19/2026",
         "paymentDate": "12/10/2026", "currency": "USD"},
        {"exOrEffDate": "08/20/2026", "type": "Cash", "amount": "$0.91",
         "declarationDate": "06/10/2026", "recordDate": "08/20/2026",
         "paymentDate": "09/10/2026", "currency": "USD"},
        {"exOrEffDate": "05/21/2026", "type": "Cash", "amount": "$0.91",
         "declarationDate": "03/10/2026", "recordDate": "05/21/2026",
         "paymentDate": "06/11/2026", "currency": "USD"},
        {"exOrEffDate": "02/19/2026", "type": "Cash", "amount": "$0.91",
         "declarationDate": "12/02/2025", "recordDate": "02/19/2026",
         "paymentDate": "03/12/2026", "currency": "USD"},
        {"exOrEffDate": "11/20/2025", "type": "Cash", "amount": "$0.91",
         "declarationDate": "09/15/2025", "recordDate": "11/20/2025",
         "paymentDate": "12/11/2025", "currency": "USD"},
        {"exOrEffDate": "08/21/2025", "type": "Cash", "amount": "$0.83",
         "declarationDate": "06/10/2025", "recordDate": "08/21/2025",
         "paymentDate": "09/11/2025", "currency": "USD"},
    ]


def test_future_ex_date_excluded_and_reported_as_next():
    last4, nxt = div.select_dividends(_msft_rows(), today=date(2026, 11, 5))
    assert [r["ex_date"] for r in last4] == [
        "2026-08-20", "2026-05-21", "2026-02-19", "2025-11-20"]
    assert nxt["ex_date"] == "2026-11-19"
    assert nxt["amount"] == 0.98
    assert sum(r["amount"] for r in last4) == 3.64


def test_yield_arithmetic_on_msft_rows():
    last4, _ = div.select_dividends(_msft_rows(), today=date(2026, 11, 5))
    # $3.64 / $500.00 close = 0.728% -> 0.7%.
    assert div.trailing_yield(last4, 500.00) == 0.7
    assert div.trailing_yield(last4, 364.00) == 1.0


def test_cash_only_filtering_and_unparseable_rows_dropped():
    rows = [
        {"exOrEffDate": "08/20/2026", "type": "Stock", "amount": "$0.91",
         "paymentDate": "09/10/2026"},
        {"exOrEffDate": "05/21/2026", "type": "Cash", "amount": "n/a",
         "paymentDate": "06/11/2026"},
        {"exOrEffDate": "not-a-date", "type": "Cash", "amount": "$0.91",
         "paymentDate": "06/11/2026"},
        {"exOrEffDate": "02/19/2026", "type": "Cash", "amount": "$0.91",
         "paymentDate": "03/12/2026"},
    ]
    last4, nxt = div.select_dividends(rows, today=date(2026, 11, 5))
    assert [r["ex_date"] for r in last4] == ["2026-02-19"]
    assert nxt is None


def test_yield_hides_without_close_but_rows_show():
    last4, _ = div.select_dividends(_msft_rows(), today=date(2026, 11, 5))
    assert div.trailing_yield(last4, None) is None
    assert div.trailing_yield([], 500.00) is None
    assert len(last4) == 4


def test_dividends_for_ticker_fake_fetch():
    async def fake_fetch(url, headers=None):
        if "dividends" in url:
            return {"data": {"dividends": {"rows": _msft_rows()}}}
        return {"data": {"tradesTable": {"rows": [
            {"close": "$499.50"}, {"close": "$500.00"}]}}}

    out = asyncio.run(div.dividends_for_ticker(
        "MSFT", fetch_json=fake_fetch, today=date(2026, 11, 5)))
    assert out["ticker"] == "MSFT"
    assert len(out["rows"]) == 4
    assert out["next_ex_date"]["ex_date"] == "2026-11-19"
    assert out["last_close"] == 500.00
    assert out["trailing_yield"] == 0.7


def test_dividends_for_ticker_bad_ticker_raises():
    try:
        asyncio.run(div.dividends_for_ticker("MSFT; DROP"))
    except ValueError as exc:
        assert "Invalid ticker" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_dividends_for_ticker_fetch_failure_hides():
    async def failing_fetch(url, headers=None):
        raise RuntimeError("network down")

    out = asyncio.run(div.dividends_for_ticker(
        "MSFT", fetch_json=failing_fetch, today=date(2026, 11, 5)))
    assert out["rows"] == []
    assert out["trailing_yield"] is None
