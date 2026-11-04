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
  compare mode. The second briefing runs for its
  LATEST quarter, not the base's: calendar quarter
  labels only fit December year-end companies, and
  forcing the base's label onto a January year-end
  company (Nvidia's quarters end Jan/Apr/Jul/Oct)
  invents a quarter it never reported and fails
  NOT_REPORTED_YET — proven live Nov 4 (NVDA +
  Q3 2026). The comparison names both quarters
  and warns when they differ; a user who wants an
  older quarter for the second company can still
  pick it with the quarter picker first and compare
  from there (latest-vs-latest is the default).
- Claim shape fix (found by the same verification):
  briefing table rows carry `claim`, not `text`
  (the Analysis shape parseClaim expects). Without
  a fallback every row parsed to a blank metric
  and the comparison collapsed to one nameless
  row with dashes in the headline table. Fixed in
  claimValueMap: `text: c.text ?? c.claim ?? ""`.
  Known Batch 7 gap this surfaced: companies with
  non-calendar fiscal quarters (NVDA: quarter
  ended 2026-07-26) get the fallback label, so the
  quarter picker hides for them — full fiscal
  support would need Scout to accept period-end
  dates, not just "Qn YYYY".
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
