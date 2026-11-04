# ADR 031 — Directory expansion 109 → 149

## Context

Nov 4, 2026, Tej: "Applovin, Dutch Bros etc — alot of tickers are
missing." The directory had grown by accretion (61 → 101 → 109) and
was missing prominent US names a visitor would expect, including
large-caps (PayPal, Block, Fortinet, MSCI, Amphenol) and popular
mid-caps (AppLovin, Dutch Bros, Reddit, SoFi, Rivian).

## Decision

Add 40 companies, all verified at SEC before admission:

APP, BROS, RDDT, SOFI, DKNG, AFRM, CVNA, DUOL, TOST, XYZ, PYPL, WING,
SHAK, CAVA, SG, ELF, CROX, DECK, AXON, APH, HIMS, UPST, U, FICO, MSCI,
FTNT, ROKU, LYFT, RIVN, DOCU, ZM, DAL, UAL, LUV, H, KDP, HSY, CL, KMB,
SYY.

Verification method (Nov 4, 2026, scripted, not by memory): each
ticker resolved in SEC `company_tickers.json`, then its submissions
feed checked for recent 10-Q and 10-K forms. All 40 passed both.
This is the admission test going forward: a ticker joins the
directory only if SEC shows it filing 10-Qs, because Scout's EDGAR
flow assumes 10-Q/8-K. Foreign filers stay out on the same rule
(TSM, ASML, NVO, SHOP, ONON, BIRK, cruise lines, and the like) —
their absence is deliberate, not an oversight.

Two corrections found by the check:

- Block, Inc. no longer trades as SQ — it is **XYZ**. The directory
  carries XYZ, and the generator gained an optional `note` field so
  Block's page reads "Formerly traded as SQ." (that line is what
  makes an "SQ" search find it). The note support lives in
  `scripts/generate_companies.py` (`note_line` in the page template);
  only XYZ uses it so far.
- The hero hint count moves 109 → 149 in the same batch. It must be
  updated on every future directory change.

Mechanics: `companies.json` 149 rows; the generator re-run produced
149 pages + index + sitemap (150 URLs). The re-run was proven
no-churn for the existing 109 pages (sha256 before/after: only the
directory index changed), so the Batch 12 page uploads in flight are
unaffected. This batch's upload is: companies.json, the 40 new
pages, the directory index, the sitemap, the generator script, the
hero hint (web/index.html), and this ADR — followed by an AI Search
full re-sync (the instance crawls the sitemap) and a live query
proof ("AppLovin" → ORCL-style top chunk for APP; "Dutch Bros" →
BROS).

Held for a later batch (not verified in this pass): VEEV, HUBS,
ANSS, TYL, CEG, VST, AAL, GIS, K, APO, BX, KKR, ARES, SIRI, LCID.
