# ADR 023 — Critic FAIL final states

## Problem

When the Critic failed attempt 1, the UI handled it well:
the Critic card showed the reasons, status "Revising",
and the Analyst went back to work. But when attempt 2
(the last attempt) also failed, the terminal state was
wrong in three ways:

1. The stream's error event carried only a stringified
   exception, so the frontend could not tell a Critic
   refusal from a transport failure.
2. The frontend marked the *working agent* failed — and
   after a FAIL the working agent is the Analyst — so
   the Analyst card looked crashed while the Critic card
   sat on "Revising" forever.
3. The error banner guessed at the cause ("If this says
   Critic FAIL…") instead of stating it.

## Change

- `mesh/orchestrator_async.py`: new `error_event(e)`
  helper. A `CriticFailed` becomes
  `{"event": "error", "error": str(e), "verdict": "FAIL",
  "issues": e.issues}`; every other exception stays a
  plain error event. The verdict logic itself is
  untouched.
- `apps/orchestrator/worker_main.py`: the stream's
  except block emits `error_event(e)`.
- `web/app.js`: on an error event with verdict FAIL,
  `showCriticFail` sets the Critic card to failed with
  the final reasons, leaves the Analyst done, and shows
  a banner stating plainly that nothing was published.
  Other errors keep the previous generic path.
- Attempt-1 copy ("Analyst is revising") was verified
  against the pipeline: attempt 2 re-runs the Analyst
  only, never the Scout — so the copy was already
  correct and is unchanged.

## What is NOT live-proven

The full stream-FAIL UI cannot be proven live without
a briefing that naturally fails — and no ticker
currently fails (the Visa case that used to fail is
fixed). What is proven: unit tests for `error_event`,
the Critic gate still FAILing bad packs (probe), and
the frontend code path by inspection plus syntax
check. Do not claim the FAIL UI itself was seen live
until a real failing briefing exercises it.
