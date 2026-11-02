# ADR 018 — Company-name search via Cloudflare AI Search

## Status
Accepted and verified live Nov 2, 2026.

## Context
Tej asked for a search box where the user types a company NAME
instead of a ticker, using Cloudflare AI Search's capabilities.
AI Search searches content you index — it has no native ticker
knowledge — so the design indexes a company directory and
searches that.

## Decision
- `web/companies/`: one short page per company (61 US
  large-caps, domestic SEC filers only — ADRs/foreign filers
  excluded because Scout's EDGAR flow assumes 10-Q/8-K).
  Each page leads with the company name and "Ticker: X" in
  plain text, short enough to index as a single chunk that
  always contains the ticker. `scripts/generate_companies.py`
  regenerates pages + index from `companies.json`.
- A web-crawler AI Search instance `companies` in the default
  namespace, with the namespace public endpoint enabled
  (`ns-<id>.search.ai.cloudflare.com/search`, plus
  `/chat/completions` and `/mcp` which the search box does
  not use). Endpoint locked down: `instances_allowed` only
  `["companies"]`, rate limit 60 req/min, `authorized_hosts`
  only `agent-mesh-earnings.pages.dev`.
- The search box (homepage, above the ticker box) POSTs
  `{messages: [{role: "user", content: query}]}` on button /
  Enter only — never per keystroke — with per-query session
  caching. Suggestion cards show name + ticker; tapping one
  fills the ticker box and runs the briefing. The ticker box
  stays as fallback; no-match state says so plainly.

## What failed first: Discover crawling
The instance was first created as Discover (web crawl from
the site root, include rules `/companies/`, `/companies/*`).
It indexed 0 documents twice — including after the homepage
gained a footer link to `/companies/`. The crawler never
reached the directory; the most likely mechanism is that it
only follows links from in-scope pages and the root is out
of scope, but the exact rule is unverified. Lesson: do not
rely on Discover + include rules for a directory the root
does not already link into scope; give the crawler the URL
list directly.

## Fix: sitemap parsing
`web/sitemap.xml` (directory URLs only — the search box
searches the directory, not the briefing UI) + `web/robots.txt`
pointing at it, both emitted by `generate_companies.py`. The
instance was deleted and recreated with the same ID as
Sitemap parsing (parse type cannot be edited in place).
Result: 62 URLs collected, 62 fetched, 0 errors, 62 indexed,
62 vectors. Two recreation gotchas, both confirmed twice:
deleting an instance resets the namespace allowlist to 0
(re-add `companies` and re-verify), and the dashboard's sync
dropdown offers no Monthly option (15 min–24 h only), so the
instance syncs every 24 h instead of monthly — harmless for
a near-static directory.

## Live response shape (probed Nov 2, 2026)
`{success, result: {query_kind, search_query, chunks:
[{text, item: {key: <page URL>}, score, instance_id}]}}`.
The parser (`web/app.js`) takes the ticker from the chunk's
page URL (`/companies/<TICKER>`) or from "Ticker: XXX" in
its text; the directory-index chunk matches neither and is
skipped. Chunks arrive score-ordered; up to 5 are shown.

## Verification
End-to-end live: typing "Intel" produced the "Intel
Corporation (INTC)" suggestion; clicking it filled the
ticker box with INTC and started a briefing (Scout card left
Waiting for Working). Full briefing completion via that path
reuses the already-proven briefing pipeline and was not
separately awaited.

## Costs and open questions
Directory ingestion is a few thousand tokens (negligible vs
the 5M/month free pool); each search is 1 semantic query
against the 1,000/month pool — plenty for personal use, and
button-only search + session caching protect it. What the
dashboard does past the free allotment on a no-card account
is still unverified: the dashboard shows the limits but no
overage note, and no claim is made here. The `/mcp` and
`/chat/completions` namespace endpoints are enabled but
unused by the search box — future Q&A/agent use, not this
batch.
