# ADR 071 — Batch 49: Feature 17 same-company quarter compare

Date: 2026-11-05. Status: built + harness-tested; live check
waits on the next Pages deploy (frontend-only, no Worker
change).

## Change

The compare box switches mode when the search picks the base
ticker instead of refusing it:
- `renderSameTickerQuarters()` shows the base company's
  quarter buttons — the same `prevQuarters` /
  `prevFiscalQuarters` functions as the quarter picker, driven
  by the base briefing's facts — with the prompt "Compare
  <TICKER> with an earlier quarter". No earlier quarters in the
  facts shows that as an empty note.
- `startSameQuarterCompare(label)` refuses the base's own
  quarter inline ("That's the quarter already shown — pick an
  earlier one."), otherwise runs that quarter's briefing
  through the existing cache + pipeline path (`getBriefing`)
  and renders the comparison with the title "<TICKER>: <QA> vs
  <QB>" (short quarter labels; the quarters line still carries
  the full labels and warns that they differ). The growth race
  chart is skipped for same-ticker compares — it has nothing to
  draw when both sides are the same company.
- Error side: `getBriefing` / `runStream` gained an optional
  `onError` parameter. The stream error event (FAIL and
  NOT_REPORTED_YET), the display-error path, the cached-render
  failure, and the POST fallback all route the message to
  `onError` when one is given, instead of the standalone error
  UI. The same-quarter handler renders the comparison with the
  base side's figures and the failure named on the second side
  (`renderComparisonError`) — it never falls back to the latest
  quarter. Standalone runs are untouched (onError is null).
- Share link: the same-quarter run writes
  `?ticker=<T>&compare=<T>&compareQuarter=<label>` (+
  `&quarter=` for the base quarter, as today); the 2-way run
  deletes a stale `compareQuarter`. The load path's parsing is
  now the pure `parseShareLink(search)`; a same-ticker link
  without a valid quarter label restores the base briefing
  only (an invalid label is dropped, never run as latest —
  `getBriefing` would turn a bad label into ""). The
  auto-compare consumption (`consumePendingAutoCompare`) routes
  a `compareQuarter` to `startSameQuarterCompare`.

## Tests

- Harness `~/workspace/overnight-probes/same_quarter_compare_harness.js`:
  **19/19 PASS** (mode prompt + 3 quarter buttons; same-quarter
  refusal runs nothing; quarter pick calls getBriefing with the
  label; same-ticker title; growth race skipped; share link
  carries compareQuarter and round-trips from the written URL;
  error comparison shows the failure with the base side intact
  and both quarters named; invalid compareQuarter dropped;
  2-way link still parses; fiscal compareQuarter parses;
  NVDA-style fiscal buttons use short labels). Two harness bugs
  found along the way (a stub formatter, a URL `+` vs `%20`
  encoding assumption) — both were harness-side, not app code.
- `node --check web/app.js` clean.
- Live check (MSFT latest vs Q2 2026 — both sides render with
  correct quarter labels, claims aligned by metric, and the
  share link restores the pair) waits on the Pages deploy.
