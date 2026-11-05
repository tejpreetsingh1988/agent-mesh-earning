"""Feature 15 — shareholder yield data leg
(mesh/shareholder_yield.py).

Unit: formula on the real MSFT fixture inputs (probed live
2026-11-05 — buybacks $21.0B trailing 4Q, shares 7,426,194,552,
last close $493.95, dividends 4 x $0.91); trailing window is
exactly 4 quarters; any-missing-input hides the card; wrong
series unit hides the card; approximation label present. The
route and the frontend card land in the follow-up batch.
"""
import asyncio

from mesh import shareholder_yield as sy


def _series(values):
    return [{"period_end": f"2026-0{i}-30", "value": v}
            for i, v in enumerate(values, start=1)]


def test_formula_on_msft_fixture_inputs():
    # Buybacks: 7.415 + 4.627 + 4.579 + 4.379 = $21.0B.
    buybacks = sy.trailing_sum(_series([5_650_000_000, 7_415_000_000,
                                        4_627_000_000, 4_579_000_000,
                                        4_379_000_000]))
    assert buybacks == 21_000_000_000
    dividends = 3.64 * 7_426_194_552
    market_cap = 493.95 * 7_426_194_552
    assert sy.shareholder_yield(buybacks, dividends, market_cap) == 1.3


def test_trailing_window_is_exactly_four():
    assert sy.trailing_sum(_series([1, 2, 3])) is None
    assert sy.trailing_sum(_series([1, 2, 3, 4])) == 10
    assert sy.trailing_sum(_series([1, 2, 3, 4, 5])) == 14  # last 4 only


def test_yield_hides_on_missing_input():
    assert sy.shareholder_yield(None, 1, 100) is None
    assert sy.shareholder_yield(1, None, 100) is None
    assert sy.shareholder_yield(1, 1, None) is None
    assert sy.shareholder_yield(1, 1, 0) is None


def _fake_history(ticker, metric):
    async def _run():
        if metric == "buybacks":
            return {"unit": "USD", "series": _series([5_650_000_000, 7_415_000_000,
                                                       4_627_000_000, 4_579_000_000,
                                                       4_379_000_000])}
        return {"unit": "shares", "series": _series([7_428_434_704,
                                                      7_425_545_491,
                                                      7_426_194_552])}
    return _run()


def _fake_dividends(ticker, today=None):
    async def _run():
        return {"rows": [{"ex_date": f"2026-0{i}-20", "amount": 0.91,
                         "pay_date": f"2026-0{i}-10"} for i in range(1, 5)],
                "next_ex_date": None, "trailing_yield": 0.7, "last_close": 493.95}
    return _run()


def test_assembler_fake_fetch_msft():
    out = asyncio.run(sy.shareholder_yield_for_ticker(
        "MSFT", history_fetch=_fake_history, dividends_fetch=_fake_dividends))
    assert out["shareholder_yield"] == 1.3
    assert out["buybacks_trailing_usd"] == 21_000_000_000
    assert out["dividends_trailing_usd"] == 3.64 * 7_426_194_552
    assert out["market_cap_usd"] == 493.95 * 7_426_194_552
    assert "latest share count" in out["approximation_note"]


def test_assembler_hides_when_dividends_short():
    async def short_divs(ticker, today=None):
        return {"rows": [{"ex_date": "2026-08-20", "amount": 0.91,
                          "pay_date": "2026-09-10"}],
                "next_ex_date": None, "trailing_yield": None, "last_close": 493.95}

    out = asyncio.run(sy.shareholder_yield_for_ticker(
        "MSFT", history_fetch=_fake_history, dividends_fetch=short_divs))
    assert out is None


def test_assembler_hides_on_wrong_unit():
    async def wrong_unit(ticker, metric):
        return {"unit": "USD_B", "series": _series([1, 2, 3, 4])}

    out = asyncio.run(sy.shareholder_yield_for_ticker(
        "MSFT", history_fetch=wrong_unit, dividends_fetch=_fake_dividends))
    assert out is None


def test_assembler_bad_ticker_raises():
    try:
        asyncio.run(sy.shareholder_yield_for_ticker(
            "MSFT; DROP", history_fetch=_fake_history,
            dividends_fetch=_fake_dividends))
    except ValueError as exc:
        assert "Invalid ticker" in str(exc)
    else:
        raise AssertionError("expected ValueError")
