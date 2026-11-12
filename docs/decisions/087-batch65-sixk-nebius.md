# ADR 087 — Batch 65: 6-K support for foreign private issuers (Nebius)

## Status
Accepted — Nov 12, 2026. Built, tested, not yet pushed (folds
into the Wave-2 push with Batches 61 + 64).

## Context
Nebius (NBIS) reported Q3 2026 on Nov 12 and was missing from
the app entirely. It is a Dutch foreign private issuer (CIK
1513845): 249× 6-K and 16× 20-F, ZERO 10-Q/10-K/8-K. The
pipeline was built on 10-Q XBRL + 8-K 99.1, so NBIS was
structurally out of reach — the Scout's earnings-filing pick
fell back to the most recent filing overall (the 6-K shell,
which carries no numbers) and the EDGAR overlay found no
companyfacts. CoreWeave, reported the same week, was the
opposite case: a normal 10-Q filer that was simply never added
to the directory.

## Decision
Three changes, all deterministic, no LLM in the numbers path:

1. **Earnings-filing identification gains a 6-K branch**
   (`mesh/edgar.py`, `mesh/async_tools.py`, and the TS MCP
   server `mcp-server/src/edgar.ts`). When the Item 2.02 8-K
   walk finds nothing, the newest 6-K whose shell says
   "Exhibit 99.1 ... financial results" is picked, and its
   Exhibit 99.1 is resolved via the filing's index.json
   (Batch 62's matcher) as the primary document. The 8-K path
   is untouched for 10-Q filers.

2. **Release-text facts** (`mesh/release_facts.py`, new). The
   6-K exhibit's Financial Highlights table is parsed
   deterministically: each row is (prior quarter, current
   quarter, change%, prior nine-months, current nine-months,
   change%) in $ millions. A row is emitted only when it
   matches that shape AND its stated change% agrees with
   (cur-prev)/|prev| (or the signed-denominator reading, which
   is how releases report a narrowing loss as "-69%") within
   1.5 points, or is "n/m" on a loss base. Labels are anchored
   to line starts — an unanchored "Revenues" also matches
   "Cost of revenues", whose row self-checks fine at 412%
   and would have emitted cost figures as revenue (caught by
   the tampered-row test). Facts are labelled "SEC EDGAR
   (6-K exhibit 99.1 — release text)", never presented as
   XBRL. The quarter end is read from the release itself
   ("three and nine months ended September 30, 2026") — a
   6-K's submissions reportDate is the filing date, not the
   period end. The Scout runs this branch only when the XBRL
   overlay found nothing and the filing is a 6-K (both
   mirrors), and the requested-quarter path now admits 6-K
   candidates with the same consensus confirmation.

3. **Downstream legs fall back to 6-K in the same window**
   (`mesh/kpi.py::pick_earnings_8k`, `mesh/past_reactions.py::
   earnings_8k_candidates`): earliest 6-K within 75 days of
   the quarter end when no 8-K fits. The KPI leg then resolves
   the exhibit from the 6-K's index exactly as for 8-Ks.
   The Analyst gains two adjusted metrics
   ("adjusted_ebitda", "adjusted_net_income") in its growth
   list, labelled as adjusted, never merged with the GAAP
   series. No operating-margin claim fires for NBIS (no
   operating-income row in the highlights table) — the
   Analyst states that in risks rather than deriving it.

## Consequences
- NBIS Q3 2026 parses to revenue $980.8M (+571% YoY, prior
  $146.1M), net loss -$37.5M (prior -$119.6M), adjusted
  EBITDA $465.8M (prior -$5.2M), adjusted net income $90.9M
  (prior -$100.4M), shares 292,902,405 — all verified against
  the exhibit fixture. Full suite 354 passed, 1 skipped
  (incl. 12 new 6-K tests: parser, tampered-row rejection,
  6-K filing pick, KPI/past-reactions fallbacks, sync+async
  Scout packs, requested-quarter pack, Analyst adjusted
  claims). Proof copies synced; parity tests pass.
- Directory grows 168 -> 169 (NBIS added; pages + sitemap
  regenerated). AI Search needs a re-sync for the 169 URLs
  after the push.
- Known limits: the TS MCP server's earnings pick still does
  no Item 2.02 walk (pre-existing divergence from the Python
  path — the deployed pipeline uses Python, so the product
  is unaffected); a 6-K filer whose release leads with prose
  before the highlights table still parses (the table is
  found by label, not position), but a release with a
  differently-shaped highlights table emits no facts and
  says so in Data notes instead of guessing.
- Live proof owed after the push: a fresh NBIS briefing must
  carry the release-text claims (Revenue +571%), the KPI
  items, and the 6-K note in Data notes.
