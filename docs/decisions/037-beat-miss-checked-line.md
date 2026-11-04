# ADR 037 — EPS beat/miss badge + checked-in line

## Status
Accepted Nov 4, 2026 (Batch 19 of the product sweep).

## Context
A briefing's verdict paragraph carries the story, but the
one-glance question — did EPS beat or miss consensus? — was
buried in the claims table, and nothing on the article said
how long the four-agent check took. Both answers already
existed in the page's data; they just were not surfaced.

## Decision
- The badges row gains a beat/miss badge, computed in
  `render()` from the same consensus claim and the same
  "reported vs forecast" regex as the EPS chart, so the badge
  can never disagree with the chart: "▲ EPS beat",
  "▼ EPS miss", or "EPS met", with the two numbers in the
  title attribute. It hides when no consensus claim exists.
  Beat/miss get green/red tint classes with dark-mode
  overrides; "met" reuses the neutral outline badge.
- The story card gains a "Checked in {total}s by Scout,
  Analyst, Critic, Writer." line. `render()` hides it, so a
  cached briefing never claims a fresh check; the run's
  completion site shows it — the stream briefing event with
  its computed total, or the POST fallback with the time
  since the run started. The compare run's article shows the
  second briefing's line, matching the article it displays.
- No new data, no new pipeline call, no backend change: the
  badge reads held claims, the line reads the run clock.

## Consequences
- The badge is only as good as the consensus claim: a
  briefing whose consensus comparison is unavailable shows
  no badge rather than a guessed one.
- The checked line's seconds are wall-clock run time
  (stream + fallback when the fallback ran), the same total
  the conductor strip shows — never a per-agent sum.

## Verification fix (Nov 4, 2026)
Live verification found the badge missing on a fresh DUOL
briefing that HAS a consensus claim ("EPS vs consensus …
-1.8% ($0.54 vs $0.55)"), while the checked line worked —
so the Batch 19 code was live and the badge's parse was
wrong, not the deployment. Root cause: the shared
"reported vs forecast" regex `/([\d.]+)\s*vs\s*([\d.]+)/`
cannot match a detail like "$0.54 vs $0.55", because the
second "$" is not a digit, dot, or space — the match fails
and both the badge and the EPS chart (which uses the same
regex) silently show nothing. The pre-existing chart bug
surfaced with the badge because they share the parse.
Fix: both sites now use
`/\$?([\d.]+)\s*vs\s*\$?([\d.]+)/`, which parses the DUOL
detail to 0.54 vs 0.55 ("▼ EPS miss", agreeing with the
story) and still matches $-free details. The MSFT run in
the same verification had no consensus claim at all, so
its badge was correctly hidden — that part was not a bug.
