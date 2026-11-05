# ADR 038 — Directory expansion 149 → 162

## Context

Nov 4, 2026, Tej: "keep expanding." The previous batch held
15 candidates unverified (ADR 031); this batch runs that
held list through the admission test.

## Decision

Add 13 companies, all verified at SEC before admission:

VEEV, HUBS, TYL, CEG, VST, AAL, GIS, APO, BX, KKR, ARES,
SIRI, LCID.

Verification method (same as ADR 031, scripted, not by
memory): each ticker resolved in SEC
`company_tickers.json`, then its submissions feed checked
for a recent 10-Q and a recent 10-K. All 13 passed both
(most recent 10-Qs Aug–Nov 2026, most recent 10-Ks
Feb–Jul 2026).

Two held candidates FAIL and stay out:

- ANSS (Ansys) and K (Kellanova) are absent from the
  current SEC ticker map, so they fail admission. Both
  are former tickers, delisted — the map is the test, and
  a ticker the SEC no longer lists cannot feed Scout's
  EDGAR flow. They are not re-pitched without a live
  SEC listing.

Mechanics: `companies.json` 162 rows; the generator
re-run produced 162 pages + index + sitemap (163 URLs).
No churn on the existing 149 pages (sha256
before/after: only the directory index changed), and
the sitemap base stays on the old host
(agent-mesh-earnings.pages.dev) deliberately — AI
Search keeps crawling that sitemap, so no instance
recreate is risked. The hero hint moves 149 → 162 in
the same batch; it must be updated on every future
directory change. This batch's upload is:
companies.json, the 13 new pages, the directory index,
the sitemap, the hero hint (web/index.html), and this
ADR — followed by an AI Search full re-sync and a live
query proof.
