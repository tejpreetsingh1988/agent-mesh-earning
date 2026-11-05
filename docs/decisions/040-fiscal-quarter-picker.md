# ADR 040 — Quarter picker for non-calendar fiscal companies

## Status
Accepted Nov 4, 2026 (Batch 20 of the product sweep).

## Context
The Batch 7 quarter picker only worked for calendar
companies: it derived previous quarters from the label
("Q3 2026" → Q2, Q1, Q4), so a fiscal label like
"quarter ended 2026-07-26" (Nvidia, Costco, Apple)
parsed to nothing and the picker hid itself. Fiscal
companies are a large share of the directory, so the
picker's absence there was a visible gap, not an edge.

## Decision
Backend (`mesh/scout.py`, vendored into the scout
Worker proof by the sync script):
- `_quarter_end_from_label` now also accepts the fiscal
  fallback label: "quarter ended 2026-07-26" →
  "2026-07-26" (validated as a real date). The whole
  Batch 7 requested-quarter flow — 8-K selection in the
  75-day window, facts truncated to the quarter end,
  NOT_REPORTED_YET when nothing matches — then works
  unchanged for fiscal quarters.
- Two exact-date comparisons that silently broke fiscal
  quarters now compare fiscal months instead, via a
  shared `_same_fiscal_month` helper: Nasdaq reports a
  fiscal quarter as month/year, so its month-end
  (2026-07-31) and a fiscal actual end (2026-07-26)
  are the same quarter. This fixes (a) the filing
  confirmation in `_pick_quarter_filing` — without it,
  a fiscal quarter fell back to the earliest in-window
  8-K with a "could not confirm" note — and (b) the
  consensus guard, which discarded the consensus row
  for every fiscal quarter and would have left the
  beat/miss badge and EPS chart empty. Month
  granularity is backward compatible: calendar
  quarters confirm exactly as before (their month-end
  IS the quarter end), and a different month still
  mismatches.
- No orchestrator change: it passes `quarter`
  through opaquely. Only a docstring mentions fiscal
  labels now.

Frontend (`web/app.js`):
- `getBriefing` accepts fiscal labels alongside
  "Qn YYYY" (previously it stripped anything else to
  latest, so even a shared fiscal link silently ran
  the latest quarter).
- `renderQuarterPicker` gains a fiscal branch:
  previous quarters come from the briefing's own
  Scout facts — real period ends, newest first,
  excluding the current quarter, max 3 — because
  fiscal calendars are irregular (52/53-week years,
  Sunday/Saturday ends) and date arithmetic would
  invent quarter ends. Buttons show the short label
  ("Jul 2026") but carry the full fiscal label.
  Calendar companies keep the existing computed
  path unchanged. The facts are available on both
  paths: stream runs set `lastScoutFacts` from Scout
  events, cache restores set it from the saved entry.
- A fiscal picker shows only quarters that exist in
  the facts — never a dead click — unlike the
  calendar path, which can offer an unreported
  quarter that returns NOT_REPORTED_YET.

## Consequences
- The picker now appears for fiscal companies on
  both fresh runs and cached briefings.
- A fiscal quarter briefing keeps its consensus
  comparison (beat/miss, badge, EPS chart), which
  the old exact-date guard would have dropped.
- The 75-day 8-K window and 50-filing limit from
  Batch 7 still bound old fiscal quarters the same
  way they bound old calendar ones.

## Verification fix (Nov 4, 2026 — after the first live
## verification FAILED)

The first live verification (NVDA, earningsbrief.pages.dev)
showed the picker but every fiscal click fell back to the
latest quarter with "Unrecognized quarter label", and no
consensus. Diagnosis, in order:

1. The frontend HAD shipped (fiscal buttons rendered), and
   the Scout HAD received the fiscal label (it quoted it in
   the note) — so the deployed Scout Worker was serving
   pre-Batch-20 code. The local repo and proof copies were
   both already fixed and identical; the Workers Build for
   the Batch 20 scout commit had not produced a live
   deployment. The re-upload below doubles as the fresh
   build that unsticks it (same remedy as the Nov 2 Critic
   stale-serving incident: a never-built commit).
2. A real code gap Batch 20 missed: `mesh/scout_async.py`
   — the cloud path — hand-mirrors the consensus guard
   with an EXACT-date comparison (`cons_end !=
   requested_end`) while the sync guard went
   month-granular. Its module docstring claimed quarter
   logic is imported so fixes land in both paths at once;
   that was false for this guard. Fixed to
   `_same_fiscal_month` (imported from scout.py), docstring
   corrected, and a regression test added
   (`test_async_fiscal_quarter_keeps_month_granularity_consensus`:
   April row "Apr/2026" → month-end 2026-04-30 vs actual
   end 2026-04-26 must be kept). Without this fix, the
   April briefing would still have lost its consensus even
   after the redeploy.
3. A second frontend gap in the same class: the page-load
   auto-run pre-filtered `?quarter=` to calendar labels
   only, so a shared fiscal link (or a reload) dropped the
   quarter and restored the latest briefing. Fixed by
   passing the parameter through and letting
   `getBriefing`'s own validation (which accepts fiscal
   labels) decide.

Open after this fix (observed, not part of it): the live
NVDA picker showed Apr/Oct/Jul 2025 but no Jan 2026, though
the picker logic itself is correct (distinct fact periods <
current, newest first). The likely cause is a facts gap, not
a picker bug: on the cloud path facts are EDGAR-only, and
NVDA's Jan-2026 (Q4 FY2026) row depends on the derived-Q4
reconstruction from the 10-K. To confirm on re-verification
by inspecting the latest briefing's fact periods; if Jan
2026 is still absent, it is a separate EDGAR-derivation
follow-up, not a quarter-switching failure.

## Re-verification attempt 2 (Nov 4, 2026, 22:31-22:59 MST) — BLOCKED, two separate failures

Part 1 PASS: both fix markers confirmed on GitHub main by
content, not line counts — `if cons_end and not
_same_fiscal_month(cons_end, requested_end):` in
mesh/scout_async.py, and `getBriefing(baseTicker, qParam ?
qParam.trim() : "");` in web/app.js (the deployed Pages
app.js contains the same line). The earlier line-count
mismatch (report said 526 lines, local file 349) is
therefore a reporting artifact, not a wrong upload.

Part 2 BLOCKED by TWO failures, neither of which is the
fixed code:

1. The live UI starts NO briefing at all. Across many
   attempts (10:32-10:59 MST, fresh tabs, search-match
   clicks, recent-briefing clicks, direct ?ticker= loads,
   reloads) the page loads and search works, but clicking
   only changes the URL — the main area stays "No run
   yet. Pick a company to start the pipeline." with no
   spinner, agent cards, or error. A bot-challenge
   specialist ruled out a challenge (no wall, no prompt;
   page renders fully). The site worked at 9:29 PM the
   same evening; the only site change since is the one-line
   app.js load-path fix, whose click path is identical to
   the 9 PM working version — so a code regression in the
   click path is unlikely and the cause is undiagnosed.
   Local code review found the pre-conductor path fully
   guarded (show/readBriefingCache/hideCacheBanner all
   null/try-caught; destroyChart/makeChart guard a missing
   Chart global) except for render() in the cache branch.
   A console + storage diagnosis task is dispatched to
   name the exact throw (console errors verbatim, Chart /
   tsParticles presence, ame_briefing_* key parse results,
   whether the stream request fires).

2. The deployed Scout Worker still serves OLD code. The
   verification task's direct-stream probe used the SHORT
   label "Apr 2026", which the backend never accepted, so
   that probe was inconclusive — but a direct curl with
   the CORRECT label ("quarter ended 2026-04-26") still
   returns "Unrecognized quarter label 'quarter ended
   2026-04-26' — using the most recent reported quarter."
   and the July briefing. The Orchestrator calls the Scout
   at mesh-scout-proof.tejpreetsingh1988.workers.dev by
   default; the fix commit (d9b1403) has not produced a
   live deployment there as of ~11:00 PM. The same
   diagnosis task checks the dashboard build status for
   mesh-scout-proof (and mesh-orchestrator-proof). MSFT
   direct-stream control still works (Q2 2026, facts to
   2026-06-30), so the Orchestrator and calendar path are
   fine.

Minor flag, unconfirmed: the report says clicking the
recent "NVDA · Jul 2026" chip produced
?quarter=quarter+ended+2025-07-27 (2025, not 2026).
Treat as a possible report paraphrase until the UI works
again and the chip's actual data-q can be read; do not
call it a bug on this evidence alone.

Next: act on the diagnosis — a named console throw gets
fixed + re-uploaded + re-verified; a failed/skipped Scout
build gets rebuilt/redeployed; stale serving gets the
Nov 2 remedy (a fresh never-built commit). Batch 20
stays open and the held bundle stays held until a clean
re-verification passes.

## Root causes found (Nov 4, 2026, 23:02-23:10 MST) — diagnosis task + local code read

1. Render throw (the UI failure): the fix upload staged
   the LOCAL web/app.js, which by then contained the held
   batches' render calls (takeaways, KPIs, diagram, fine
   print, ownership), against the DEPLOYED Batch 20
   index.html, which lacks those sections. render() set
   innerHTML on $("b-takeaways") — always non-empty for a
   real briefing — and threw "Cannot set properties of
   null (setting 'innerHTML')" on EVERY render. Cached
   briefings died silently (URL changed, nothing else);
   fresh runs died after all four agents completed and
   were misreported as "Connection lost". Proven by a JPM
   run (Scout 3.3s, Analyst, Critic PASS, Writer 15.7s,
   charts drawn) ending in that exact error box. Fix:
   setHTML/setText null-guards on every render write, a
   marked isDisplayError so runStream's catch shows the
   real error instead of the connection-lost copy, and a
   cache-branch catch with an honest message. Harness
   19/19, node --check clean. Upload of app.js ONLY
   dispatched (the held index.html stays held).
2. Worker builds (the stale Scout): ALL five Python
   Workers fail at Deploy with "ERROR uv version at least
   0.13.4 required, have 0.12.23." + "ERROR Update uv
   with 'uv self update'." The same commit failed 5 times;
   Batch 20's builds 2h earlier also Failed/Skipped. The
   Batch 20 backend and the fix NEVER deployed — the
   stale-Scout finding was a build failure, not queue
   latency. Fix: prepend `uv self update && ` to each
   project's deploy command (dashboard task dispatched,
   with retries). If `uv self update` fails, the fallback
   is pinning pywrangler in the repo.

Lesson (also in AGENTS.md): never upload a file whose
local state includes unshipped-batch code without checking
what else it drags in — a one-line fix upload silently
shipped a whole frontend ahead of its HTML. And a
"stale deploy" diagnosis must check the build STATUS on
the dashboard before assuming queue latency.

## Hotfix landed (Nov 4, 2026, 23:13-23:14 MST)

The render hotfix is on main as commit b974a5b
("Hotfix: guard render against missing held-batch
sections + honest render errors"): web/app.js, 2287
lines, `function setHTML` confirmed at line 46. The
served Pages app.js was independently verified by curl
the same night: 2287 lines, setHTML present,
isDisplayError present, and the load-path fix line
present — Pages has deployed it. (A first upload
attempt stalled because the file was not granted to
that browser task; the lesson is in AGENTS.md and the
replacement task with the grant landed the file in
~1 minute.) The uv dashboard fix is still pending at
this writing; the full Batch 20 re-verification runs
once its report lands.

## Gate expanded (Nov 4, 2026, 23:50 MST – Nov 5, 2026, 00:20 MST)

Round 2 of the uv fix SUCCEEDED: all five Python Workers are
Ready at 100% traffic (deploy command now `pip install
--upgrade uv && cd cloudflare-proof/<name> && uv run
pywrangler deploy`). The render hotfix is live on Pages. The
direct-stream probe then proved the Batch 20 backend live:
NVDA April (correct label) → quarter ended 2026-04-26, 21
facts, Critic PASS, verdict "Revenue up 85.2% YoY; operating
margin 65.6%", NO "Unrecognized quarter label". But the same
probe surfaced two correctness bugs in the shared evidence
path that the picker exposed rather than caused — so the gate
does NOT close on the picker alone:

1. The latest "earnings filing" was the most recent 8-K of ANY
   kind (NVDA July → Sep 3, 2026 non-earnings 8-K; April → Jun
   30, 2026 non-earnings 8-K), so consensus + price reaction
   anchored to wrong dates. And the requested-quarter candidate
   window (limit 50) had aged out NVDA's real May 20, 2026
   earnings 8-K.
2. The derived-Q4 reconstruction paired fiscal years by
   end-date calendar year: a −$17.3B "revenue" fact shipped in
   live packs while the real Q4 FY2026 row (Jan 2026) never
   appeared — which also made April's QoQ claims stale
   (Jul→Oct 2025) and kept "Jan 2026" out of the picker.

Both are fixed as ADR 052 (Item 2.02 earnings-8-K walk; 300-row
candidate window; derived-Q4 keyed by `fy`), coded + tested
(9 new tests; suite 232 passed, 1 skipped) and proven on live
EDGAR data (Jan 2026 $68.127B, Jan 2025 $39.331B derived).
They ride the combined upload; the Batch 20 re-verification
runs against the uploaded code as part of that upload's live
checks (April: report_date 2026-05-20, consensus present with
no Nasdaq forecast, QoQ Apr vs Jan, picker offers Jan 2026;
latest: report_date 2026-08-26, consensus $2.22 vs $2.09).

## uv fix round 1 FAILED (Nov 4, 2026, 23:12-23:27 MST)

`uv self update` failed identically on all five
retried builds, verbatim: "error: Self-update is only
available for uv binaries installed via the standalone
installation scripts." / "If you installed uv with
pip, brew, or another package manager, update uv with
`pip install --upgrade`, `brew upgrade`, or similar."
So the build environment's uv is pip-installed, not
standalone — self-update was never going to work. The
saved deploy commands now start `uv self update && `
and every project is still failing. Round 2 (dispatched
23:27 MST): replace that prefix with
`pip install --upgrade uv && ` on all five projects,
save, retry, report. If pip itself fails, the next
fallback is the standalone installer
(`curl -LsSf https://astral.sh/uv/install.sh | sh` +
PATH export) — NOT yet tried. The repo does not pin
pywrangler anywhere (cloudflare-proof/*/pyproject.toml
lists only fastapi/pydantic + workers-py dev deps), so
`uv run pywrangler` fetches the latest pywrangler,
which is what raised the uv >= 0.13.4 requirement.
