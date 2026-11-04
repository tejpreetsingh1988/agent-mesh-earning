# ADR 028 — Pipeline transparency: ledger, baton rail, honest failure states

Date: 2026-11-04
Status: implemented locally, upload + live verification pending

## Problem

After clicking a company, the page showed four "Waiting" cards, a
decorative loop, and a ticking seconds counter — and nothing that said
what was actually working, what was next, or what had just been handed
over. The left-rail graphic was the worst part: packets circled a
pentagon forever (even when idle), which implied continuous circulation
and parallelism that the pipeline does not have — the run is strictly
Scout → Analyst → Critic → Writer, once. It also used a four-colour
gradient stroke, which is exactly the look this project avoids.

Separately, a mid-stream break marked the working agent "Failed" even
though the run might still have been completing server-side, and a
Critic gate refusal left the Writer card on "Waiting" forever.

## Decision (frontend only — no backend change)

1. **Optimistic plan on click.** `getBriefing` renders the full 4-step
   plan in the same tick as the click: all four cards "Queued" with
   what each waits for, and a now-strip reading "Starting — Scout is
   first · Step 1 of 4 · Next: Analyst · Usually 30–90s". The range is
   honest (measured briefings run ~30–90s); no point estimate, no
   percent bar — there is no measurable denominator to percent against.
2. **Now-strip.** The conductor card becomes the strip: at every event
   it reads "Now: {agent} — {verb}" plus "Step n of 4 · Next: {next}".
   On completion: "Done — briefing ready · Ready in Ns · 4 of 4 steps".
3. **Baton rail, straight not loop.** The SVG pentagon is gone. The
   left rail is four nodes in a row (Scout → Analyst → Critic → Writer)
   joined by segments. Exactly one node is active; earlier nodes show
   a check; a segment fills only when that handover really happened.
   The chronological handover feed underneath is unchanged.
4. **Handover lines between ledger rows.** On each real transition a
   line appears between the two cards, e.g. "Scout → Analyst · 24 facts
   · took 4.2s", "Critic → Writer · PASS", "Critic → Analyst · FAIL,
   revising (attempt 1)". Lines are filled only on the event, never
   in advance. Card bodies still carry the full output (pivot tables,
   claim blocks) as they arrive.
5. **Gate ≠ crash ≠ disconnect.**
   - Gate refusal (attempt-2 FAIL): Critic takes the amber "Stopped by
     check" state, Writer becomes "Skipped", the critic→writer line
     reads "blocked — gate refused to publish", and the strip gets an
     amber edge. No retry button — re-running reproduces the refusal.
   - Server error event: the working agent is "Failed" (a real failure).
   - Lost connection mid-stream: the working step becomes "Paused"
     (its dot stops pulsing), the strip reads "Connection lost — live
     stream stopped · The run may still be completing on the server ·
     Ledger frozen, not failed", and the error banner gains a "Run
     again" button. That button is an explicit fresh run, not an
     automatic retry, and it never appears for a server verdict.
6. **POST fallback honesty.** When the stream never speaks, the cards
   say so ("No step-by-step view — the live stream did not speak")
   instead of sitting on "Queued" while the final briefing loads.

## What this does NOT do

- No server-side resume. "Run again" starts a fresh pipeline; a true
  resume (run_id checkpointing, re-running only failed steps) needs
  Orchestrator changes and is a separate batch.
- The Critic FAIL UI still has no natural live exercise (no ticker
  currently fails); the gate rendering is harness-verified, not
  live-seen. Same caveat as Batch 4.
- `prefers-reduced-motion` already silenced the old loop animations;
  the rail's active pulse is added to that same list.

## Verification

- `node --check web/app.js` clean.
- Node harness `/tmp/b9_harness.js` (fake DOM): 21 checks pass —
  reset-to-queued, rail progression scout → analyst → critic →
  writer → conductor (checks, filled segments), handover-line
  fill-on-event only, gate state + writer skipped + amber strip +
  no retry, disconnect retry visible, server-verdict retry hidden.
- Live verification pending: upload, then a browser check that a
  fresh (uncached) briefing shows the queued plan on click, the
  now-strip stepping through, handover lines filling, and the rail
  ending all-checked.
