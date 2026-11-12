# ADR 080 — Batch 58: cache banner refreshes on a new save

Date: 2026-11-05. Status: built + harness-verified; rides the
Batches 51–55 push (frontend-only, does not touch the pipeline
or any route, so it cannot confound the post-push live checks).

## Problem

The Nov 5 UI pass caught a minor wart: after a fresh NVDA
run completed, the page banner still showed the OLD saved
timestamp (6:12:44 AM) — the banner timestamp does not
refresh when a new briefing saves. `saveBriefingCache` wrote
the new entry but nothing updated a visible banner.

## Change

- `web/app.js::saveBriefingCache` captures `savedAt` once,
  and after writing re-renders the banner with the fresh entry
  when the banner is visible for the same ticker+quarter.
  A hidden banner stays hidden; a banner for a different
  ticker or quarter is untouched. The refresh is wrapped in
  its own try/catch — best-effort, like the cache write.
- `web/app.js::showCacheBanner` stamps the banner element
  with `dataset.ticker` / `dataset.quarter` so a later save
  can tell whether it is the banner to refresh.
- `~/workspace/overnight-probes/cache_banner_harness.js`:
  7 checks — same ticker+quarter refreshes to the new time
  and stays visible; other-ticker and other-quarter banners
  untouched; hidden banner stays hidden and unrefreshed.

## Verification

- Harness: **7/7 PASS**.
- Push-manifest re-verification: `web/app.js` vs remote main
  is +140/−1 — the 51–55 additions (+122) plus Batch 58
  (+18), the single removal being the inlined
  `savedAt: Date.now()` replaced by the shared const.
- Live check (after the push: run a fresh briefing while its
  cached banner is showing, confirm the banner carries the
  fresh save time) waits on the push.
