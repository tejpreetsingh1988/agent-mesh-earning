"""Who's trading it (Batch 24) — company-level trading activity,
shown as reported, never interpreted.

Three sources, settled by live CORS probes Nov 4, 2026:
- Nasdaq insider-trades + institutional-holdings: the API sends
  NO Access-Control-Allow-Origin header, so a browser fetch is
  blocked — these two are fetched Worker-side (this module, via
  worker_http) behind the Orchestrator Worker's /ownership
  route. Both endpoints are undocumented Nasdaq API routes in
  the same family as the earnings calendar; any failure yields
  null and the card hides.
- Veridion Markets disclosures: the www host sends
  Access-Control-Allow-Origin: *, so the browser fetches it
  directly (its own IP, not the Worker's shared egress IPs,
  against the free tier's 60 requests/hour). The frontend does
  that fetch; this module does not touch Veridion.

Framing rules (binding): no "bullish insiders", no "suspicious
trades", no ranking politicians by amount. Order is the
source's order (recent first). Politician amounts are the
disclosed RANGES, verbatim — the midpoint the API also returns
is never parsed into the output at all, so it cannot leak into
a card. Fund figures carry their 13F lag label; insider figures
carry their Form 4 derivation label.
"""
import asyncio
import re

from .edgar import UA as EDGAR_UA
from .worker_http import fetch_json as _afetch_json

NASDAQ_HEADERS = {"Accept": "application/json", "User-Agent": EDGAR_UA}
TICKER_RE = re.compile(r"^[A-Z]{1,5}$")


def _rows(block):
    """Rows of a Nasdaq {headers, rows} block, or [] when absent."""
    if not isinstance(block, dict):
        return []
    rows = block.get("rows")
    return rows if isinstance(rows, list) else []


def _find_row(rows, prefix):
    for r in rows:
        if isinstance(r, dict) and str(r.get("insiderTrade", "")).startswith(prefix):
            return r
    return {}


def parse_nasdaq_insiders(data):
    """Shape a Nasdaq insider-trades payload into the card model.
    None when the payload has no usable rows (card hides)."""
    if not isinstance(data, dict):
        return None
    data = data.get("data") or {}
    trades = _rows((data.get("numberOfTrades") or {}))
    shares = _rows((data.get("numberOfSharesTraded") or {}))
    table = data.get("transactionTable") or {}
    trows = _rows((table.get("table") or {}))
    if not trades and not trows:
        return None
    buys = _find_row(trades, "Number of Open Market Buys")
    sells = _find_row(trades, "Number of Sells")
    total = _find_row(trades, "Total Insider Trades")
    bought = _find_row(shares, "Number of Shares Bought")
    sold = _find_row(shares, "Number of Shares Sold")
    net = _find_row(shares, "Net Activity")
    recent = []
    for r in trows[:8]:
        if not isinstance(r, dict):
            continue
        recent.append({"insider": str(r.get("insider", "")).strip(),
                       "relation": str(r.get("relation", "")).strip(),
                       "date": str(r.get("lastDate", "")).strip(),
                       "type": str(r.get("transactionType", "")).strip(),
                       "shares": str(r.get("sharesTraded", "")).strip(),
                       "price": str(r.get("lastPrice", "")).strip(),
                       "held": str(r.get("sharesHeld", "")).strip()})
    return {"buys3": buys.get("months3", ""), "buys12": buys.get("months12", ""),
            "sells3": sells.get("months3", ""), "sells12": sells.get("months12", ""),
            "total3": total.get("months3", ""), "total12": total.get("months12", ""),
            "bought3": bought.get("months3", ""), "bought12": bought.get("months12", ""),
            "sold3": sold.get("months3", ""), "sold12": sold.get("months12", ""),
            "net3": net.get("months3", ""), "net12": net.get("months12", ""),
            "total_records": table.get("totalRecords"),
            "recent": recent}


def _position_rows(block):
    out = []
    for r in _rows(block):
        if isinstance(r, dict):
            out.append({"label": str(r.get("positions", "")).strip(),
                        "holders": str(r.get("holders", "")).strip(),
                        "shares": str(r.get("shares", "")).strip()})
    return out


def parse_nasdaq_funds(data):
    """Shape a Nasdaq institutional-holdings payload. None when
    the ownership summary is absent (card hides)."""
    if not isinstance(data, dict):
        return None
    data = data.get("data") or {}
    summary = data.get("ownershipSummary") or {}
    if not isinstance(summary, dict) or not summary:
        return None

    def _val(key):
        v = summary.get(key) or {}
        return v.get("value", "") if isinstance(v, dict) else ""

    ht = data.get("holdingsTransactions") or {}
    top = []
    for r in _rows((ht.get("table") or {}))[:8]:
        if not isinstance(r, dict):
            continue
        top.append({"owner": str(r.get("ownerName", "")).strip(),
                    "date": str(r.get("date", "")).strip(),
                    "shares": str(r.get("sharesHeld", "")).strip(),
                    "change": str(r.get("sharesChange", "")).strip(),
                    "change_pct": str(r.get("sharesChangePCT", "")).strip(),
                    "value": str(r.get("marketValue", "")).strip()})
    return {"ownership_pct": _val("SharesOutstandingPCT"),
            "shares_outstanding": _val("ShareoutstandingTotal"),
            "holdings_value": _val("TotalHoldingsValue"),
            "positions": _position_rows(data.get("activePositions")),
            "new_sold_out": _position_rows(data.get("newSoldOutPositions")),
            "holders_total": ht.get("totalRecords"),
            "shares_held_total": ht.get("sharesHeld", ""),
            "top": top}


async def fetch_ownership_async(ticker: str, fetch_json=_afetch_json):
    """Worker-side Nasdaq fetch for one ticker: {"ticker",
    "insiders", "funds"} with either card null on failure.
    Ticker is strictly validated — it is interpolated into the
    request URL, so anything outside [A-Z]{1,5} is refused."""
    t = (ticker or "").strip().upper()
    if not TICKER_RE.match(t):
        raise ValueError(f"Invalid ticker for ownership fetch: {ticker!r}")
    base = f"https://api.nasdaq.com/api/company/{t}"

    async def _one(path):
        try:
            return await fetch_json(f"{base}/{path}?assetclass=stocks",
                                    headers=NASDAQ_HEADERS)
        except Exception:
            return None

    ins_raw, funds_raw = await asyncio.gather(
        _one("insider-trades"), _one("institutional-holdings"))
    return {"ticker": t,
            "insiders": parse_nasdaq_insiders(ins_raw) if ins_raw else None,
            "funds": parse_nasdaq_funds(funds_raw) if funds_raw else None}
