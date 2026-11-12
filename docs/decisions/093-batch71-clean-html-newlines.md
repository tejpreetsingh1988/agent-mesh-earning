# ADR 093 — Batch 71: `_clean_html` destroyed the line structure the 6-K parser needs

## Status
Accepted. Built and tested Nov 12, 2026. Pushed in Wave-5.

## Context
The first live NBIS briefing (Nov 12, ~11:56 PST) came back
structurally fine but numerically empty: Scout REPORTED,
quarter_end 2026-09-30 correct, Critic PASS attempt 1 — but the
evidence pack held exactly one fact (shares_outstanding
292,902,405) and the briefing's verdict was "Insufficient
evidence", with an empty table, no KPIs, no diagram and a short
honest story. All four Financial Highlights rows were rejected
with "could not verify the 'Revenues' row against its stated
change%" notes.

The local Batch 65 test extracted all four rows from the vendored
fixture of the same exhibit (tm2629571d1_ex99-1.htm), so the
parser was not wrong — the input was. Reproduction on the live
exhibit proved it: `mesh/edgar.py::_clean_html` collapsed ALL
whitespace to single spaces (`re.sub(r"\s+", " ", text)`), leaving
0 newlines in the 26,554-char cleaned text, while
`mesh/release_facts.py::_label_re` anchors every row label to a
line start (`(?m)^\s*`). No label mid-text can ever match in
production text. The fixture passed only because it preserved
newlines — the test never ran the production cleaning step. The
unanchored searches (shares, quarter end) still worked live,
which is why the run looked half-right instead of fully broken.

## Decision
`_clean_html` now preserves line structure: collapse horizontal
whitespace only (`[^\S\n]+` → single space) and collapse blank
lines (`\n\s*\n+` → `\n`). The label anchoring stays — it is
the protection against matching "Revenues" inside "Cost of
revenues" (whose row self-checks fine at 412% and would emit
cost figures as revenue). Verified on the real exhibit: all four
rows extract (revenue 0.1461/0.9808, net −0.1196/−0.0375, adj
EBITDA −0.0052/0.4658, adj net −0.1004/0.0909, shares
292,902,405), missing empty. The other `_clean_html` consumers
(8-K/6-K candidate head checks, transcript excerpts, the async
mirror in `async_tools.py` which calls the same function) do not
depend on single-line text; the full suite passes unchanged.

## Consequences
- New regression test in `tests/unit/test_sixk.py`: the parser
  runs on `_clean_html(fixture)` and must extract all four rows
  plus shares. It fails on the old cleaner (0 newlines, 0 rows)
  and passes on the new one — the production cleaning step is
  now inside the test boundary.
- The live NBIS briefing must be re-run after Wave-5 deploys to
  prove the fix end to end (the Workers run the vendored proof
  copies, synced by `scripts/sync-worker-proof.py`).
- Lesson: a parser test that feeds a fixture straight to the
  parser tests the parser, not the pipeline. Any parser whose
  input passes through a cleaning step needs a test that runs
  the cleaning step too.
- Unrelated to this fix: the NBIS diagram leg failed on both
  model routes (AI Gateway 7003 + OpenRouter 429) and the CRWV
  fine-print leg returned empty — both look like model
  availability pressure at the time, not code defects; re-check
  on later runs.
- Wave-5 files: `mesh/edgar.py`, `tests/unit/test_sixk.py`,
  this ADR, and the four synced proof copies of `edgar.py`
  (scout/critic/writer/orchestrator).
