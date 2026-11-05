# ADR 050 — Fine-print section

## Status
Built Nov 4, 2026. Upload + live verification join
the held bundle behind the Batch 20 verification
report.

## Decision
A "Fine print — what's new in the filings"
section, below Company metrics, surfaces what
changed between this quarter's and last quarter's
10-Q filings (MD&A + footnotes) plus the quarter's
8-K exhibit 99.1 release, via one LLM pass. It is
LLM-surfaced, NOT Critic-verified, and never
enters the verified claims table. Every number
shown must appear verbatim in the fetched filing
text (same validator rule as the story); every
quote must appear verbatim (normalized). An item
failing either check is dropped, never patched.
No model at all is a valid hiding result.

## What was built
- `mesh/fineprint.py`: 10-Q fetch (submissions
  feed → two most recent 10-Qs with reportDate
  <= quarter_end → primary documents, stripped
  with kpi.strip_html), section extraction (MD&A
  heading to the next ITEM heading; footnotes
  heading the same way; a missing heading yields
  an empty section, never a failure), sentence
  diff (exact normalized match = unchanged,
  difflib >= 0.8 = changed, else new), ranking
  (new+keyword first — litigation, impairment,
  restatement, covenant, default and friends —
  then new, then changed, capped at 12 passages),
  one LLM pass down the story chain (Workers AI
  → gateway models → direct OpenRouter; sync
  twin for the Docker path), parse + validate
  (quote verbatim, why_it_matters numbers
  digit-checked against the full text, capped at
  5 items), best-effort wrappers that yield
  ([], []) on any failure.
- Sentence granularity, not paragraphs: a real
  finding from the build. strip_html collapses
  blank lines, so stripped 10-Q text has no
  paragraph breaks to split on — the first
  version's blank-line splitter returned one giant
  paragraph per section and the diff was useless.
  Sentences (split on sentence-ending punctuation
  + capital/digit/quote, fragments < 60 chars
  dropped) are the unit instead. The 99.1 release
  opening (first 4,000 chars) rides along as
  context; Release items link the exhibit, MD&A /
  Notes items link this quarter's 10-Q.
- Writer plumbing mirrors KPIs exactly: repo
  handler calls fineprint_for_pack_sync
  (best-effort, belt-and-suspenders); the proof
  transform replaces it with
  fineprint_for_pack_async on the same ai/key
  context; write_briefing takes
  fine_print_result; Briefing gains `fine_print`.
  Vendor list += fineprint.py. The transform's
  string replaces were extended (not rewritten),
  and the generated proof handler was grep-verified
  to carry the async call — the Batch 22 caution.
- Frontend: `<section id="sec-fineprint">` after
  Company metrics (reuses .card/.list/.meta, no
  new CSS), renderFinePrint wired in render(),
  "## Fine print" in the .md export with the
  provenance line. Old cached briefings without
  fine_print simply show no section.

## Tests
`tests/unit/test_fineprint.py` (6 tests:
section extraction + ITEM boundaries, diff +
keyword-first ranking, parse fences/bad JSON,
validation drops for bad quotes and bad numbers,
cap at 5, end-to-end sync pack step with faked
fetches + LLM, hiding on LLM failure); frontend
harness `/tmp/b30_harness.js` 8/8; full suite
211 passed, 1 skipped.

## Live verification (after upload)
A fresh briefing on a company with a busy 10-Q
(MSFT): the Fine print section appears with up
to 5 items, each quote verifiable in its linked
filing, and the section hides on a briefing
whose filings yield nothing. The 10-Q fetch cost
(two full filings per briefing) is watched on the
first live runs — if Writer latency grows
materially, the section fetch gets a tighter cap
before it ever blocks a briefing (it cannot: the
wrapper swallows everything).
