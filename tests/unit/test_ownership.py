"""Batch 24: Nasdaq ownership parsers + Worker-side fetch with
fakes. Fixtures are small excerpts of the real MSFT payload
shapes probed live Nov 4, 2026 (not the full files, so tests
stay hermetic)."""
import asyncio

import mesh.ownership as own


def _insiders_payload():
    return {"data": {
        "numberOfTrades": {"rows": [
            {"insiderTrade": "Number of Open Market Buys", "months3": "14", "months12": "28"},
            {"insiderTrade": "Number of Sells", "months3": "15", "months12": "49"},
            {"insiderTrade": "Total Insider Trades", "months3": "29", "months12": "77"}]},
        "numberOfSharesTraded": {"rows": [
            {"insiderTrade": "Number of Shares Bought", "months3": "391,234", "months12": "402,800"},
            {"insiderTrade": "Number of Shares Sold", "months3": "282,946", "months12": "386,636"},
            {"insiderTrade": "Net Activity", "months3": "108,288", "months12": "16,164"}]},
        "transactionTable": {"totalRecords": 159, "table": {"rows": [
            {"insider": "HOOD AMY", "relation": "Officer", "lastDate": "10/13/2026",
             "transactionType": "Sell", "sharesTraded": "7,305",
             "lastPrice": "$544.80", "sharesHeld": "555,396"}]}}}}


def _funds_payload():
    return {"data": {
        "ownershipSummary": {
            "SharesOutstandingPCT": {"label": "Institutional Ownership", "value": "84.29%"},
            "ShareoutstandingTotal": {"label": "Total Shares Outstanding (millions)", "value": "7,426"},
            "TotalHoldingsValue": {"label": "Total Value of Holdings (millions)", "value": "$3,479,216"}},
        "activePositions": {"rows": [
            {"positions": "Increased Positions", "holders": "3,358", "shares": "245,215,566"}]},
        "newSoldOutPositions": {"rows": [
            {"positions": "New Positions", "holders": "253", "shares": "47,863,783"}]},
        "holdingsTransactions": {"totalRecords": 6632, "sharesHeld": "6,259,834,813 Total Shares Held",
                                 "table": {"rows": [
                                     {"ownerName": "Vanguard Group Inc", "date": "12/31/2025",
                                      "sharesHeld": "717,942,580", "sharesChange": "15,955,898",
                                      "sharesChangePCT": "2.273%", "marketValue": "$399,032,486"}]}}}}


def test_parse_nasdaq_insiders():
    out = own.parse_nasdaq_insiders(_insiders_payload())
    assert out["buys3"] == "14" and out["buys12"] == "28"
    assert out["net3"] == "108,288" and out["net12"] == "16,164"
    assert out["total_records"] == 159
    assert out["recent"][0]["insider"] == "HOOD AMY"
    assert out["recent"][0]["price"] == "$544.80"
    assert own.parse_nasdaq_insiders({}) is None
    assert own.parse_nasdaq_insiders({"data": {}}) is None


def test_parse_nasdaq_funds():
    out = own.parse_nasdaq_funds(_funds_payload())
    assert out["ownership_pct"] == "84.29%"
    assert out["shares_outstanding"] == "7,426"
    assert out["holders_total"] == 6632
    assert out["positions"][0]["label"] == "Increased Positions"
    assert out["new_sold_out"][0]["holders"] == "253"
    assert out["top"][0]["owner"] == "Vanguard Group Inc"
    assert out["top"][0]["change_pct"] == "2.273%"
    assert own.parse_nasdaq_funds({"data": {}}) is None


def test_fetch_ownership_async_shapes_and_failure():
    async def fake_fetch(url, headers=None):
        if "insider-trades" in url:
            return _insiders_payload()
        if "institutional-holdings" in url:
            return _funds_payload()
        raise AssertionError(url)

    out = asyncio.run(own.fetch_ownership_async("MSFT", fetch_json=fake_fetch))
    assert out["ticker"] == "MSFT"
    assert out["insiders"]["buys3"] == "14"
    assert out["funds"]["ownership_pct"] == "84.29%"

    async def failing_fetch(url, headers=None):
        raise RuntimeError("Nasdaq down")

    out2 = asyncio.run(own.fetch_ownership_async("MSFT", fetch_json=failing_fetch))
    assert out2 == {"ticker": "MSFT", "insiders": None, "funds": None}


def test_fetch_ownership_async_validates_ticker():
    async def unused(url, headers=None):
        raise AssertionError("must not fetch")

    try:
        asyncio.run(own.fetch_ownership_async("MSFT; DROP", fetch_json=unused))
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")
