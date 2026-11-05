# ADR 049 — Price reaction via Nasdaq daily closes (flipped from Stooq Nov 4, 2026)

## Status
Built Nov 4, 2026. Upload + live verification join
the held bundle behind the Batch 20 verification
report.

## Decision
The market-reaction section is fed by Stooq daily
closes (free, no key, one CSV per briefing:
`https://stooq.com/q/d/l/?s=<ticker>.us&i=d`),
replacing yfinance. The Analyst definition is
unchanged in spirit and strengthened in one rule:
base = last trading-day close on or before the
report date, reaction = first trading-day close
after it. The old exact-match rule silently
produced nothing when the report date was a
weekend or holiday (no close row for that date);
the "next row after report date" rule skips
weekends/holidays by construction.

## Why Stooq replaces yfinance here
On the Worker, yfinance is not installed, so the
lazy import raised before any I/O and Scout
recorded the market step in `missing` — which is
why cloud briefings showed an empty market section
by design. Stooq is plain HTTPS + CSV: the sync
path uses urllib, the cloud path uses
worker_http.fetch_text (pyfetch on the Worker),
so the same tool works on both paths. The HOOD
HTTP 500 on the Docker market-mcp path (yfinance
failing for HOOD, root cause never investigated)
goes away as a side effect — the Docker path now
uses Stooq too.

## What was built
- `mesh/market.py`: `parse_stooq_csv` (pure,
  order-agnostic, bad rows skipped) +
  `reaction_payload` (window trim: up to 5 rows
  before base through 5 rows after reaction, so
  a full Stooq history never bloats the pack
  through four Worker calls) + sync
  `get_price_reaction` (urllib, 10s timeout,
  error dict on failure — Scout records it in
  `missing`, the briefing continues).
- `mesh/async_tools.py`: `async_get_price_reaction`
  no longer routes through `_market_tool` (which
  calls the sync function — dead on Workers) but
  fetches via worker_http and shares the parser +
  payload. The other market tools (profile,
  quarterly history) stay on `_market_tool` —
  Docker-only, not in the briefing path.
- `mesh/analyst.py` + `mesh/critic.py`: the
  selection rule changed in lockstep in both
  (the Critic recomputes with the same rule, or
  it would fail valid claims). Claim text and
  window format are unchanged
  ("Regular-session close change (D1 -> D2):
  +X.X% ($A -> $B)"), so the frontend market
  section needs no change — it renders
  briefing.market_reaction, which is the claim.
- Labels (binding): the payload window string
  carries both caveats — closes are UNADJUSTED
  (a split or large dividend between the two
  days can distort the move) and daily closes
  cannot show the after-hours move. The Analyst
  claim text already says "NOT an after-hours
  move."

## Stooq reachability — CLOSED: flipped to Nasdaq
## (Nov 4, 2026)

The live-browser read came back the same evening:
the tab "loaded" the exact CSV URL but rendered a
completely blank page — no header, no rows, no
error, no block notice, no CAPTCHA. Three routes,
three failures: VM curl timeout (0 bytes), text
fetch network error, real browser blank. Stooq is
blocked for automated access generally, and the
fetcher flipped to Nasdaq historical closes, as
this ADR pre-committed. The parser, payload,
Analyst and Critic changes are source-agnostic
and stand unchanged; only the fetcher and the
source label moved ("Stooq (free)" ->
"Nasdaq (free)"), with the same unadjusted +
no-after-hours caveats.

Nasdaq shape, proven by a live VM curl the same
day (GOOGL, Oct 20–Nov 3, 2026, 11 rows):
`data.tradesTable.rows`, newest first, `date`
MM/DD/YYYY, `close`/`open` "$"-strings, `volume`
comma strings, trading days only. The new
`parse_nasdaq_closes` converts to the same
ascending ISO [{date, close, open, volume}] the
window code consumes; both the sync (urllib) and
async (worker_http) fetchers use the shared
`nasdaq_window` (60 days before through 30 days
after the report date) and `NASDAQ_URL`.

Flip side-finding (Batch 26): real Nasdaq rows
carry MM/DD/YYYY dates, and `history._parse_date`
was ISO-only — it dropped every real row, so the
vs-chart's total-return path would have silently
hidden on live data. Fixed with an MM/DD/YYYY
fallback (ISO stays first); covered by a new
history test with real-format rows.

Live proof still rides a post-deploy briefing
check (GOOGL Q3 2026: reported after close Oct
28, 2026 — expect a 10-28 -> 10-29 window, now
from Nasdaq closes $324.89 -> $283.82).

## Tests
`tests/unit/test_nasdaq_reaction.py` (8 tests:
Nasdaq parser order/bad rows, window trim,
weekend report Friday->Monday, missing reaction
note, Critic recompute + tamper catch, sync +
async fake-fetch parsing); `test_mcp_tools.py`'s
market test now fakes Nasdaq JSON;
`test_history.py` gains the MM/DD/YYYY
total-return test; the Stooq test file was
removed. Full suite after the flip: 223 passed,
1 skipped.
