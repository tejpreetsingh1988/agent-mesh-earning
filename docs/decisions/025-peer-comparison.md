# ADR 025 — Peer comparison

## Change

Frontend only — no backend, Worker, or pipeline change.
Every briefing article gains a "Compare with" picker
(local directory matches, instant, deliberately not
logged to the search log: a compare pick is not a
briefing search and must not feed "most searched").

- Picking a second company runs it through the
  normal pipeline via `getBriefing(ticker, quarter,
  onDone)` — the new optional callback fires after
  the briefing renders on both the stream and POST
  paths, and is skipped for the cache banner in
  compare mode. The second briefing runs for the
  SAME quarter as the base briefing (Batch 7's
  quarter plumbing), so the comparison is
  like-for-like; a mismatched quarter label shows a
  warning line instead of silently comparing.
- The comparison section shows both verdicts, a
  headline table (Revenue YoY growth, Operating
  margin, EPS vs consensus), and an all-claims
  table aligned by metric with "—" for a claim only
  one company has. Values are the backend's own
  claim values (parseClaim's rounded value plus its
  direction arrow); the frontend computes no numbers
  and aligns only.
- Comparing a company with itself is refused with
  an inline note. A new run (or a plain cached
  render) hides the comparison; a compare run
  rebuilds it through onDone. The share link after
  a compare points at the second briefing alone —
  the comparison view itself is not in the URL.
- Cost, stated plainly: a comparison runs the full
  pipeline a second time (~30–60s for the second
  briefing, cached afterwards like any briefing).
