# ADR 024 — Quarter selector

## Problem

Scout accepted a `quarter` payload field ("Q2 2026") but
used it only as a label override (line: `quarter_label =
quarter or derived`). Passing Q2 2026 returned
latest-quarter data mislabeled Q2 2026 — worse than
refusing, because the numbers looked right.

## Change

Scout now honors the quarter (sync + async, mirrored):

- `_quarter_end_from_label`: "Q2 2026" -> "2026-06-30"
  (calendar quarters, the reverse of `_quarter_label`).
- Filing selection: 8-Ks filed in the 75 days after the
  quarter end, confirmed by probing consensus — the
  first candidate whose Nasdaq fiscal quarter ending
  equals the requested end wins. At most 5 keyless
  Nasdaq probes, usually 1 (the Alpha Vantage
  cross-check only runs when a key is configured,
  never on Workers). No confirmation -> earliest
  candidate + a missing note saying so. No candidate
  -> NOT_REPORTED_YET naming the quarter.
- Facts truncated to periods <= the requested end;
  no fact for the quarter end itself ->
  NOT_REPORTED_YET (nothing to brief, not latest data
  under an old label).
- Consensus for a different quarter end is discarded
  (beat/miss must not use it). The quarter-end
  derivation chain is overridden by the requested end.
- An unparseable label falls back fully to latest,
  including the label (a test caught "bogus" surviving
  as quarter_label).
- Price reaction and transcript already key off the
  selected filing's date and the quarter label, so
  they follow the quarter with no change.

## Plumbing

- Orchestrator Worker: `GET /tasks/stream?ticker=X
  &quarter=Q2%202026` and POST `/tasks/send`
  {"ticker", "quarter"} pass the quarter to the Scout
  payload (`_scout_payload`). The pipeline itself
  never sees the quarter — the Scout closure carries
  it — so no orchestrator signature changed.
- Frontend: after a briefing renders, an "Earlier
  quarters" picker offers the three previous calendar
  quarters derived from its label (plus Latest when
  viewing an older quarter). Cache keys carry the
  quarter (`ame_briefing_<TICKER>_<QUARTER>`), with a
  one-time fallback to the pre-quarter legacy key for
  latest reads; share links carry `?quarter=` when
  set. An unparseable label hides the picker.
- Docker/local orchestrator path: unchanged, still
  latest-only (its scout call passes no quarter).
  Cloud is the live product.

## Known limits

- The 8-K window is the recent-filings list (limit
  50): quarters older than that window cannot be
  selected and return NOT_REPORTED_YET honestly.
- History covers 8 quarters; older quarters return
  NOT_REPORTED_YET for lack of facts.
- The fallback filing's transcript may miss (safe)
  if the filing was not the earnings release.
