# ADR 045 — Who's trading it: insiders, funds, politicians

## Decision
A "Who's trading it" section on the briefing page,
below the briefing article: three cards, all from
free keyless sources, all labeled with as-of dates
and lags. This is company-level activity, not part
of the quarter's verified briefing, and it does NOT
go through the Critic — it is disclosed activity
data, shown as reported, never interpreted (no
"bullish insiders" or "suspicious trades" framing).

## 1. Insiders — Nasdaq insider-trades (verified live)
`GET api.nasdaq.com/api/company/{TICKER}/insider-trades?assetclass=stocks`
returns a 3-month / 12-month buy/sell summary
(MSFT: 14 open-market buys in 3 months, 28 in 12)
plus a transaction table (159 records: insider,
relation, last date, transaction type, owner type,
shares traded). The table is derived from SEC
Form 4 filings; the label says so. (EDGAR Form 4
XML parsing is the primary-source fallback if
Nasdaq's endpoint ever goes away — same filings,
more work, not v1.)

## 2. Funds — Nasdaq institutional-holdings (verified live)
`GET api.nasdaq.com/api/company/{TICKER}/institutional-holdings?assetclass=stocks`
returns an ownership summary (MSFT: 84.29%
institutional), increased/decreased positions,
new/sold-out positions, and a holders table
(MSFT: 6,632 holders). These are 13F-derived, so
the card labels the lag: quarterly filings, up to
45 days stale by construction, plus Nasdaq's own
update lag. The earlier guessed endpoint
(`/api/quote/.../institutional-holdings`) 404s —
the `/api/company/` path is the working one.

## 3. Politicians — Veridion free API (verified live)
`GET veridionmarkets.com/api/v1/disclosures?ticker={TICKER}&limit=25`
returns STOCK Act rows with member, chamber,
party, buy/sell, trade date, filing date, and the
amount RANGE exactly as filed. Verified live for
MSFT: 3 rows (Pete Sessions, Lisa McClain, Maria
Elvira Salazar). Free tier, confirmed in the
response itself: no key, no signup, 25 rows per
request, 60 requests/hour per IP, cursor paging
for more. Amounts are RANGES by law — the UI
shows ranges, never midpoints-as-facts, and never
ranks members on them. The STOCK Act allows 45
days to disclose, so the card labels that lag too.
Fallbacks if Veridion ever goes away: Equibles
(free 100 req/day, needs a no-card API key) and
Bargo (anonymous lower quota, attribution
required). Disclosed Capitol is NOT a fallback —
its free credits run out into pay-per-row.

## Fetch placement and limits
- Nasdaq's endpoints are undocumented (same family
  as the earnings-calendar endpoint the consensus
  chain already uses): they work today with no key,
  and the section hides gracefully if they ever
  break — same rule as every other section.
- Veridion's 60/hour limit is per IP. A Worker
  calling it risks Cloudflare's shared egress IPs
  exhausting the quota, so v1 tries the call from
  the user's browser first (their own IP, their own
  quota) if CORS allows, else Worker-side with
  graceful hide. CORS is the open verification.
- One section, three independent fetches; any one
  failing hides only its own card.

## Open at build time
Veridion CORS headers (browser vs Worker fetch);
Nasdaq holders-table paging (6,632 rows — top N
by shares held, not the full table); whether the
section loads with the briefing or lazily after it.

## Implementation notes (Batch 24, built Nov 4, 2026)
- CORS settled by live probe, Nov 4, 2026 (and it
  split the fetch placement by source):
  * Nasdaq sends NO Access-Control-Allow-Origin
    header on either endpoint — a browser fetch is
    blocked, full stop. Nasdaq is fetched
    Worker-side: new module `mesh/ownership.py`
    (pure parsers + `fetch_ownership_async` over
    `mesh/worker_http`), behind a new
    `GET /ownership?ticker=X` route on the
    Orchestrator Worker (CORS-enabled app, same as
    the stream route). The route returns
    {"ticker", "insiders", "funds"} with either
    card null on failure; an invalid ticker is a
    400 (strict [A-Z]{1,5} validation — the ticker
    is interpolated into the request URL).
  * Veridion's host moved to www
    (bare host 307-redirects to
    www.veridionmarkets.com) and www sends
    `Access-Control-Allow-Origin: *` — the browser
    fetches it directly, so the call counts
    against the visitor's own IP on the free
    60/hour tier, never the Worker's shared egress
    IPs. No Veridion code in the Worker at all.
- Display caps: insider recent transactions 8
  (of 159 for MSFT, total named); fund top
  holders 8 (of 6,632, in Nasdaq's listed order);
  politician rows 10 of the 25 returned, most
  recent first (the API's filed_date_desc order
  is kept — never re-sorted by amount).
- Midpoint rule, structural: the JS parser
  (`veridionRows`) never reads `amount.midpoint`
  and the Python parsers never see it — the
  output shape has no midpoint field, so it
  cannot leak into a card. Ranges show verbatim
  (`$250,001 - $500,000`), falling back to a
  formatted low–high only when verbatim is
  missing.
- Loading: the section renders after the
  briefing (fire-and-forget from render(), so
  briefing latency is untouched); the three
  sources run in parallel via Promise.allSettled
  and each card hides independently on failure.
  Results memoize per ticker per page load
  (company-level data — a quarter change or a
  cache restore reuses it). Section title names
  the ticker ("Who's trading MSFT") so it stays
  unambiguous next to a comparison.
- Tests: `tests/unit/test_ownership.py` (4 tests,
  fixtures excerpted from the real MSFT payload
  shapes); frontend harness `/tmp/b24_harness.js`
  12/12; proof sync vendored ownership.py +
  edgar.py into the orchestrator proof; full
  suite 190 passed, 1 skipped. Upload + live
  verification join the held bundle behind the
  Batch 20 verification report — live checks
  then: MSFT three cards render; a ticker with
  no politician rows hides that card only.
