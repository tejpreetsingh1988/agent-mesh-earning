# ADR 017 — Progressive agent cards + honest speed

## Status
Accepted Nov 2, 2026. Built locally; upload and live
verification pending.

## Context
The user asked for overall response within 5–7 seconds, with
responses appearing on the UI as agents complete, distinct
colors/themes, named agents with accountability, and
state-of-the-art components. The previous UI showed one
skeleton until the whole briefing arrived (42–60s live), with
only a text log as evidence of progress.

## The honest speed claim
A complete live-verified briefing in 5–7 seconds
end-to-end is NOT possible: Scout's live EDGAR/Nasdaq calls
alone take ~5s, the pipeline reaches the Critic's verdict at
~9s, and the story needs a model round-trip after that.
What is achievable — and what this batch builds — is
progressive disclosure: the first agent's card lands in
~5s, each later card the moment its agent finishes, so the
page feels alive within the 5–7s window instead of spinning
for 45s. Repeat tickers can later be near-instant via
gateway caching (ADR 016); that is a separate claim from
fresh-ticker speed and must not be conflated with it.

## Decision
- Backend: `run_briefing_async` stage events now carry each
  agent's output, not just its name: scout_done carries the
  fact list (+ quarter, company, transcript status),
  analyst_done the claim list, critic_attempt the verdict
  and issue list, writer_done the story and model — each
  with duration_ms. The old count keys (facts, claims) are
  unchanged, so existing consumers and tests keep working.
- Frontend: four agent cards above the final briefing
  article, each with a display name, a role line, an
  accountability line, an accent color, a status pill
  (Waiting / Working with pulsing dot / Done with agent
  time / Failed / Revising), and a body that fills
  progressively: Scout's facts table, Analyst's claims
  table, Critic's verdict + issues, Writer's story.
  A Conductor strip above the cards shows overall status
  and elapsed time.
- Agent identities (display name — role — color —
  accountability):
  - Scout — Evidence Hunter — teal — every fact names
    its source; nothing invented.
  - Analyst — Numbers Desk — blue — every claim shows
    its arithmetic and period.
  - Critic — Truth Gate — amber — nothing ships
    without its pass; a fail stops the briefing.
  - Writer — Storyteller — violet — every figure traces
    to a claim or the transcript.
  - Conductor — Pipeline Lead — zinc — runs the agents
    in order and enforces the gate.
- The final briefing article is unchanged (the record);
  the cards are the process view. The live log stays as
  the detailed record under the cards, still downloadable.
- The POST fallback stays: if the stream fails before any
  event, the final briefing renders with a conductor note
  that live cards were unavailable for that run.
- Token-streamed stories (story text growing word by
  word) are explicitly OUT of this batch: stage-level
  progressive rendering is the requested behavior; token
  streaming is a follow-up if the Writer card's wait still
  feels long after this lands.

## Verification
After deploy: run a briefing and confirm (a) Scout's card
renders with facts at ~5s, (b) cards fill in pipeline
order, (c) Critic FAIL/retry states render if triggered,
(d) the final article still renders identically, (e) the
POST fallback still works when the stream is unavailable.
