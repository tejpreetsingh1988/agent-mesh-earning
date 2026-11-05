# ADR 046 — Shares outstanding + buybacks

Two balance/flow series the claims table and
growth chart did not have, both from EDGAR.

## Shares outstanding (cover-page tag)
- Tag: `dei:EntityCommonStockSharesOutstanding`.
  The `dei:` prefix travels with the tag string.
  New helper `split_taxonomy(tag)`: `"dei:X"` →
  `("dei", "X")`, bare tag → `("us-gaap", tag)`.
  `fetch_concept` and async `_fetch_concept`
  build the URL with the taxonomy;
  `companyfacts_tag_units` reads
  `facts[taxonomy][bare]`. Fetch signatures never
  change, so existing test fakes keep working.
- These are INSTANTS (cover dates, ~3 weeks after
  quarter end), parsed by `parse_instant_rows`
  alongside cash/ST investments (Batch 21).
- Unit conversion in BOTH sync and async paths:
  shares_outstanding → value / 1e9, unit
  `"shares_B"`. Analyst `_fmt` branch:
  `shares_B` → `"7.43B shares"` (2 decimals —
  the second decimal is ~10M shares, meaningful).
- Probe evidence (MSFT, Nov 4, 2026): HTTP 200,
  unit "shares", 69 rows, cover dates
  2025-10-23, 2026-01-22, 2026-04-23,
  2026-07-23 (10-K), 2026-10-22; values
  7,432,377,655 → 7,426,194,552 — the count
  barely moved YoY (−0.08%): buybacks ≈ offset
  by issuance. Real and interesting, not a bug.

## Instant dedupe refinement
`parse_instant_rows` now carries `fy`/`fp` on rows
and dedupes per (fy, fp) when present (latest
filed wins). An amended cover for the same
quarter has a DIFFERENT cover date, so
period_end dedupe kept both rows and broke the
Analyst's month-pairing (gap 4 instead of 3 →
no pair). Falls back to period_end dedupe when
fy/fp are absent (test fixtures).

## Buybacks
- Tags: `["PaymentsToRepurchaseCommonStock",
  "PaymentsForRepurchaseOfCommonStock"]`.
  Probe evidence (MSFT, Nov 4, 2026): 404 on the
  current tag, 200 on the older variant, 232
  rows, YTD + discrete: Q3 FY2026 discrete
  $4.627B, YTD $17.692B, FY $22.271B, Q1 FY2027
  $4.379B. `RepurchaseOfCommonStock` 404s.
- YTD-difference derivation (Batch 21 mechanism):
  the fill tuple in `apply_derived_metrics` is
  now `("depreciation_amortization",
  "operating_cash_flow", "capex", "buybacks")`.
- Side effect, noted honestly: adding the CapEx
  tag earlier also ACTIVATED the pre-existing
  (previously dead) Analyst capex-vs-operating-
  income watch. Intended behavior, now live.

## Shared derivation + async parity
- `apply_derived_metrics` lives in ONE place
  (`mesh/edgar_facts.py`), called by both sync
  `get_quarterly_facts` and async
  `async_get_quarterly_facts` — never re-fork
  it. Refactor accident, recorded so it is not
  repeated: the scripted block-move first
  absorbed the call + `result["missing"]` +
  `return result` lines INTO the new function
  (indentation), making `get_quarterly_facts`
  return None — 10 test failures. Repaired by
  restructuring: the function is defined AFTER
  `get_quarterly_facts`, the call restored inside
  it.
- Async port (`mesh/async_tools.py`): imports +=
  INSTANT_METRICS, parse_instant_rows,
  apply_derived_metrics, split_taxonomy;
  `_fetch_concept` parses the prefix; the async
  loop gained the instant branch,
  `picked_payloads`/`tag_payloads` tracking
  (incl. companyfacts synthetic payloads), and
  the `apply_derived_metrics` call. Docstring
  "up to 10 concept payloads" → 20.

## Analyst + frontend
Growth loop order now: total_revenue,
operating_income, net_income, ebitda,
operating_cash_flow, free_cash_flow,
cash_and_equivalents, short_term_investments,
cash_and_st_investments, buybacks,
shares_outstanding, cloud_revenue, gaap_eps.
The growth chart plots ALL YoY claims
generically; claimKind maps the new ones to
"claim-growth". No frontend change beyond the
Batch 21 trend-switcher work.

## Tests + verification status
- `tests/unit/test_shares_buybacks.py`, 4 tests,
  all passed Nov 4, 2026: instant (fy,fp)
  amendment dedupe; buybacks+shares end-to-end
  (discrete 4/5/6 from YTD 4/9/15; shares tag
  string is the dei-prefixed one); Analyst claims
  (Buybacks YoY +50.0%; Shares YoY −0.1% incl.
  "7.43B shares" in text); async mirror (EBITDA
  + buybacks + shares via monkeypatched
  `_fetch_concept` — proves the cloud path).
- Full suite after proof sync: 161 passed,
  1 skipped. Upload + live verification (MSFT
  all metrics + FCF sign check; DUK/AAL YTD-only
  path; NVDA fiscal grouping) are bundled with
  the Batch 21 upload, held for the Batch 20
  verification report.
- TS MCP drift: `mcp-server/src/edgar.ts` is a
  port of the OLD edgar_facts and does NOT have
  these tags/derivations — fix when the MCP
  server goes live (same note as ADR 042).
