# ADR 043 — Company-specific KPIs from the earnings release

## Decision
Company-specific metrics — Dutch Bros same-shop
sales, system-wide sales, company-operated shops,
new shops, outlook/guidance; airlines' RASM/CASM;
retailers' same-store sales; royalty and licensing
revenue where a company reports them — come from
the earnings release (8-K exhibit 99.1), NOT from
XBRL. XBRL has no reliable tags for most of these
(and where a tag exists it can be stale — see
ADR 042 on PFE's abandoned RoyaltyRevenue tag).

## Mechanism (design, not yet built)
- Source: the earnings release for the reported
  quarter. Fetch via the filing's EDGAR index JSON
  (find the exhibit 99.1 document), strip HTML,
  keep the text.
- Extraction: one LLM call over the release text
  (same story chain: Workers AI → gateway → direct
  OpenRouter), prompt asks for operating metrics as
  {name, value, unit, period} plus an outlook item.
  No per-company templates — the release decides
  what the company reports, so the section adapts
  per company. Dutch Bros yields SSS/shops; an
  airline yields RASM/CASM; a company that reports
  nothing extractable yields an empty section.
- Validation: every extracted value must appear
  verbatim (normalised) in the release text, or that
  item is dropped, never patched — the same rule as
  story quotes. The section hides entirely when
  extraction fails or yields nothing.
- Placement and labeling: a "Company metrics"
  section in the briefing article, labeled as
  release-extracted. It is NOT part of the
  Critic-verified claims table, and the Writer's
  story prompt does NOT include KPIs in v1 — the
  story validator only allows numbers from claims
  and transcript, so a KPI number in the story
  would drop the whole story. (A later step can
  extend the validator's allowed set to
  verbatim release numbers.)
- Timing: extraction runs AFTER the Critic gate,
  so a KPI failure can never block a verified
  briefing — the section just hides.
- Outlook items double as the seed for the future
  guidance tracker (guided vs delivered, per
  quarter) — stored, not just displayed.

## Cost
One extra LLM call per briefing, on the same free
chain as the story. No new data vendor, no key.

## Proof cases (when built)
BROS first (Tej's example: same-shop sales,
system-wide, company-operated, new shops,
outlook), plus one airline and one retailer.

## Open at build time
Exhibit 99.1 filename patterns per filer (index
JSON lookup, not guessing); release-text cap for
the extraction call; whether KPIs also land in D1
alongside the transcript archive (ADR 041).

## Implementation notes (Batch 22, built Nov 4, 2026)
- Module `mesh/kpi.py`: pure helpers (exhibit
  detection, HTML strip, verbatim validation, JSON
  parse, 8-K pick) + async fetch/extract (Worker
  path, via worker_http) + sync twins (Docker
  path, urllib + llm._call_openrouter). The sync
  and async paths share the pure helpers, never
  re-fork them.
- Exhibit detection settled: match the shape
  `ex(?:hibit)?[-_]?99[-_.]?1` against index.json
  filenames (BROS uses `a2026-q3_ex991.htm`).
  Release-text cap: 20,000 chars. D1 storage:
  deferred — KPIs ride in the briefing object
  (and therefore in the briefing cache) for now.
- Placement deviation from the design sketch:
  the KPI step lives in the Writer Worker's
  handler (`agents/writer/main.py`, carried to
  the proof by the sync script), not in the
  Orchestrator — the Writer Worker is the only
  one holding the LLM transports (AI binding +
  OpenRouter secret). The 8-K is picked
  independently from the pack's quarter_end
  (earliest 8-K filed after quarter end, within
  75 days), not from the Scout's filing pick, so
  it works for older-quarter views too. Schema:
  Briefing gains `kpis` + `kpi_source_url`.
- Extraction chain rule: a reply parsing to an
  empty list means the release has no qualifying
  KPIs — return [] at once, don't burn the rest
  of the chain. A reply whose items all fail
  validation tries the next model.
- Source verified live for the proof case: BROS
  Q3 2026 release (8-K filed Nov 4, 2026,
  exhibit `a2026-q3_ex991.htm`) contains
  company-operated SSS +5.4%, systemwide SSS
  +4.4%, 48 new shops, Adj. EBITDA $101.1M, and
  a 2027 goal of 250 shops. Live LLM extraction
  against it is NOT yet run — that waits for
  upload + live verification (mocked-LLM tests
  only so far). Airline + retailer proof cases
  likewise await the live run.
- Tests: `tests/unit/test_kpis.py` (15 tests);
  frontend harness `/tmp/b22_harness.js` 10/10;
  full suite 176 passed, 1 skipped after proof
  sync. Upload + live verification join the held
  bundle behind the Batch 20 verification report.
