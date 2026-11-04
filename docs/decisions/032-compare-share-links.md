# ADR 032 — Shareable comparison links (?compare=)

## Status
Accepted Nov 4, 2026 (Batch 14 of the product sweep).

## Context
Batch 8 built peer comparison, but a comparison could not be shared:
opening a link after a comparison showed only the second briefing,
because the compare run had rewritten the URL to its own ticker.
The share link had to name the pair the page actually shows.

## Decision
- A comparison renders a **Copy comparison link** button in the
  `#comparison` section. It copies the pair link
  `?ticker=BASE&compare=SECOND` (plus `&quarter=` when the base
  briefing was an older quarter), built from module state
  (`lastComparisonLink`), not from `location.href`, so a
  back-button URL is never copied by mistake. Clipboard uses
  `navigator.clipboard` with a textarea/`execCommand` fallback,
  and the button confirms with "Link copied" for 2 seconds.
- Opening `?ticker=BASE&compare=SECOND` runs the base briefing,
  then the existing compare flow automatically. A module flag,
  `pendingAutoCompare = {second, base}`, is set at load and
  consumed exactly once — in the cache branch or in
  `getBriefing`'s `finally`, after `running` is false — and only
  when the briefing that just finished is the base. A failed base
  run therefore never triggers a compare against a stale briefing.
- `startCompare` restores the pair URL after the second run:
  the compare run's own `replaceState` (ticker=SECOND) is
  overwritten with ticker=BASE, compare=SECOND, and the base's
  quarter when one was set. Manual compares get the same link.
- Validation mirrors the ticker rules: 1–10 letters, uppercased,
  self-compare refused. A bad `compare` value never breaks the
  page (the load block is wrapped in try/catch, as before).
- Compare picks stay unlogged, as in Batch 8.

## Consequences
- A shared comparison link reproduces latest-vs-latest (the
  comparison's documented mode); when the base link names an
  older quarter, that quarter is preserved and the existing
  differing-quarters warning covers the second briefing.
- The dual consume hook (cache branch + finally) exists because
  the two run paths finish differently: a cache hit returns
  before `running` is ever set, while a stream/post run clears
  `running` only in `finally` — and `startCompare`'s
  `getBriefing` refuses to start while `running` is true.
