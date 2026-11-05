# ADR 063 — Batch 41: cut the KPI prompt window to 6,000 chars

Date: 2026-11-05. Status: built + tested, upload pending.

## What Batch 40 proved (and didn't)

The Batch 40 split (KPIs alone, diagram in a second call) was
deployed live (Writer version 6a61a789) and the direct KPI call on
BROS's pack was re-run: still **0 items, 67.3s,
`workers_ai: TimeoutError`, gateway 7003s, OpenRouter 429s,
`replies: 0`**. Output length was NOT the cause — the KPIs-only
prompt still times out.

The remaining difference from the story prompt, which completes
in 60s, is input size: the KPI prompt carries 20,000 chars
(~5,000 tokens) of release text; the story prompt carries the
pack (~6,000-8,000 chars). The Workers AI free tier evidently
cannot prefill + generate on a 5,000-token input inside 60s at
the current load (whether prefill time or queueing, the observable
is the same: a 60s timeout on a 20k-char input, a completion on
a ~6k-char input).

## Change

`RELEASE_TEXT_CAP`: 20,000 → 6,000 (one line; the constant is
used only by `kpi_prompt`). The KPI prompt is now in the story
prompt's input class.

Trade-off, stated plainly: the highlights bullets (same-shop
sales, openings) sit in the first ~2,000 chars of a typical
release and survive; later-window KPIs (BROS's shop counts, AUV,
~14,000 chars in) are lost by this cut. A thinner KPI section is
better than none. A targeted second window (e.g. the non-GAAP
metrics section) is a follow-up, not this batch.

Not changed: the timeouts. The standing no-timeout-changes rule
holds for this batch; the window cut is the smaller intervention.
For the record, `AGENT_TIMEOUT_S` is 300s, so a Workers AI
timeout raise to 120s would NOT be cut off by the Orchestrator
in full runs — it remains available as a backup if the window
cut fails too.

## Tests

- New test: the KPI window is 6,000 chars — a KPI at char ~100
  is in the prompt, one at char ~10,000 is not.
- Full suite: **270 passed, 1 skipped** (was 269).
