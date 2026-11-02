# ADR 013 — AMZN story fixes: tool notes out of the story, trillion into the validator (Nov 2, 2026)

## Context

Tej's AMZN briefing (Nov 2, 2026) surfaced two story-layer
defects, both in `mesh/llm.py`:

1. The deterministic fallback's "What to watch" paragraph
   printed the pack's tool-error notes verbatim
   ("get_quarterly_history failed: No module named
   'yfinance'"), so the story read like an error log. The
   Analyst copies `pack.missing` into `risks_and_watch`, and
   the deterministic story printed all of it.
2. The Nemotron draft was dropped with "number '$1 ' appears
   in the LLM story but not in verified claims or the
   transcript". The draft had written "$1 trillion", echoing
   the call's own "1 trillion dollars in annual revenue"
   line — but `_MONEY_PCT_RE` knew only billion/million/B/M,
   so "$1 trillion" degraded to the token "$1 " (1.0), and
   "1 trillion" in the transcript matched nothing either,
   so 1.0 was not in the allowed numbers.

## Decision

- `deterministic_story` filters `risks_and_watch` through
  `_TOOL_NOTE_RE` (`No module named|failed:` — the same
  pattern the Pages frontend partitions Data notes on)
  before building the "What to watch" paragraph. If only
  tool notes remain, the paragraph is dropped, not printed
  empty. The notes themselves are unchanged everywhere else:
  they still appear under Data notes on the page, and the
  Analyst still records them.
- `_MONEY_PCT_RE` gains `trillion` in both unit positions
  (the `$`-led alternative and the bare-number alternative).
  A transcript-backed trillion now validates on both sides;
  an invented trillion still fails, because its number is
  not in the allowed set. This is a correctness fix, not a
  loosening: no previously-failing invented figure passes.
- The LLM prompt is untouched — it never included risks, so
  the LLM story could not leak tool notes in the first place.

## Verification

- `tests/unit/test_amzn_story_fixes.py`: tool notes filtered
  but real risks kept; watch paragraph dropped when only tool
  notes remain; "$1 trillion" passes against a "1 trillion
  dollars" transcript; "$5 trillion" still fails.
- Live verification is partial by construction: the filter is
  observable in the next deterministic briefing's story, and
  the trillion fix is observable only when a model next
  writes a trillion figure. Neither can be forced live without
  faking a model response, which would prove nothing.
