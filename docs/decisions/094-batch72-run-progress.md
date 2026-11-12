# ADR 094 — Batch 72: make a briefing run's progress unmistakable

## Status
Accepted. Built and tested Nov 12, 2026. Not yet pushed (Wave-6).

## Context
Tej's feedback (Nov 12): when he clicks a ticker and a briefing
run starts, the page does not clearly show which part is running.
The stage labels ("fetch filing" etc.) do not reflect the running
part, and he cannot tell what is happening without looking closely
beside each item.

The page already had the pieces — a conductor strip at the top of
the centre column (`#conductor-strip`, updated by `setConductor`
on every event) and a baton rail in the left rail (active step
pulsing, done steps green with a check, waiting steps dimmed).
Four gaps made them unreadable at a glance:

1. **The conductor strip looked identical running or idle.**
   Its dot was a static 10px muted circle and the status text was
   14px/600 — nothing in the strip itself said "running".
2. **The Critic-FAIL (revising) branch never updated the
   conductor.** While the Analyst revised claims after a failed
   check, the strip kept saying "Critic — re-checking every
   number". The status line lied about the running part.
3. **The rail had no failed state.** On a terminal Critic refusal
   the Critic step kept pulsing as "active" after the run died;
   on an upstream error the rail was never touched at all, so a
   dead run showed a live step. On a broken stream the working
   step also kept pulsing while the run was frozen.
4. **The POST fallback never said "done".** `runPost` rendered
   the briefing without updating the conductor, so the line stuck
   on its starting text; the display-error path left the last
   running step pulsing too.

## Decision
One live status line, one source of truth for its text:

- **`runStatusForEvent(name, ev, ctx)`** (pure, in `web/app.js`)
  maps every stream event to plain present-continuous words, the
  step detail, the strip state, and the rail step — from the event
  actually received, never a guessed stage. `onStreamEvent` and
  `runStream` call it instead of duplicating text.

  | Event | Status line |
  |---|---|
  | run_started | text unchanged (set on click) · dot starts pulsing |
  | scout_started | Fetching the earnings filing from SEC EDGAR… |
  | scout_done | Checking the numbers… |
  | analyst_done | Re-checking every claim… |
  | critic_attempt PASS | Writing the story… |
  | critic_attempt FAIL | Revising the claims… |
  | writer_done | Assembling the briefing… |
  | briefing | Done — briefing ready |
  | error, Critic FAIL | Stopped by check — Critic refused to publish |
  | error, UPSTREAM_ERROR | Stopped — the SEC rate-limited the request |
  | error, other | Pipeline stopped with an error |
  | connection lost / stream ended | Connection lost — live stream stopped / ended early |
  | POST fallback | Fetching the final briefing… |

  "Fetching the earnings filing" is deliberately form-neutral:
  the event carries no filing form, and a 6-K company is not a
  10-Q. Details carry the counts ("75 facts from the filing",
  "18 claims to verify", "Critic found 2 issues · Attempt 1").

- **`setConductor(text, detail, state)`** gains a state:
  `running` (amber left border, amber pulsing dot), `done`
  (green border + dot), `alert` (red dot, amber border — the
  established "stopped, not a crash" accent), `idle` (muted).
  `setConductorState(state)` applies it; `run_started` calls it
  so the dot pulses the moment the server accepts the run.
  `resetCards` clears the state on a new run.

- **`setLoop(agent, text, { failed, paused })`** gains the two
  missing rail states. A failed step is red with a ✕ and a bold
  red label; a paused step keeps its agent colour and letter,
  stops pulsing, and sits between done and waiting. The running
  step's label is now bold (800) with a ringed node; waiting
  steps dim to 0.45 (from 0.55) and explicitly exclude failed /
  paused. Every call re-derives all four steps, so a stale mark
  cannot survive into a new run.

- **`markRunFailed()`** derives the failed step from the ledger:
  the first leg whose card is not Done goes red; earlier legs
  keep Done, later legs stay waiting. When every leg is Done the
  failure is past the rail and the line shows complete instead of
  blaming a step. It is called on the error event, on Critic
  refusal, and on POST failure — the same leg rule Batch 61 set
  for the cards now holds for the rail too.

- The POST success path now says "Done — briefing ready" but
  does **not** touch the rail: no step-by-step view happened
  there, so no step may claim Done.

## Consequences
- No new dependencies, no new DOM ids, design language kept
  (semantic tokens, amber/green/red already in use). Reduced
  motion stills the conductor dot as well as the rail nodes.
- Harness `~/workspace/overnight-probes/run_progress_harness.js`:
  CSS audit (15 checks) + the mapping for every event including
  both UPSTREAM_ERROR shapes + stubbed-DOM rail/conductor tests
  (advance, refusal, upstream error, all-done, frozen, reset,
  state transitions) + wiring checks that every pipeline branch
  uses the mapping. **142 passed, 0 failed.**
- Full pytest suite: **368 passed, 1 skipped** (the stamp test
  caught the changed app.js/styles.css hashes; re-stamping
  index.html fixed it — stamps now styles.css `v=a53265ef`,
  app.js `v=b20137a8`).
- Wave-6 files: `web/app.js`, `web/styles.css`,
  `web/index.html` (re-stamped), this ADR. The harness lives in
  `~/workspace/overnight-probes/` and is not pushed.
- Not done here: a rendered visual check of the strip/rail in a
  browser (no headless Chromium on the VM); the parent agent
  verifies live after the Wave-6 push.
