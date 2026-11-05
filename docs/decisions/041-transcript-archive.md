# ADR 041 — Transcript archive (design)

## Status
Design, Nov 4, 2026. Prompted by Tej: "scrape every
website and save their earnings transcript in the
database… we can use these transcripts in several ways
in the future."

## Decision
Build a transcript archive in D1, in two phases. It is
an archive for agent analysis first; the UI shows
excerpts and derived analysis, never a republished
full third-party transcript.

## Phase 1 — capture what Scout already fetches (no new scraping)
Every briefing already fetches a transcript excerpt
(Motley Fool, via the existing transcript module).
The Orchestrator POSTs that excerpt, best-effort, to
a new log Worker (modelled on the search-log Worker)
after the briefing completes — never blocking the
briefing if the log call fails. Table `transcripts`:
ticker, quarter_label, quarter_end, source_url,
excerpt, fetched_at. The archive then grows
organically from real briefings, at zero new
scraping risk and zero new cost.

## Phase 2 — backfill full text (new scraping, rate-limited)
A backfill job fetches Motley Fool transcript pages
for directory companies' recent quarters and stores
the full text, still served to users as excerpts and
analysis only. Sources in priority order: Motley
Fool (primary, existing candidate-URL module);
company investor-relations pages where Fool has no
transcript. Excluded deliberately: Seeking Alpha
(login/paywall), audio-only webcasts (no text to
store), and any source that blocks automated reads.
Gaps are recorded, not papered over: a missing
transcript is a missing row, and the UI says so.

## Phase 2b — audio fallback: transcribe when no text exists
Added Nov 4, 2026, per Tej: when no text transcript
exists for a ticker+quarter, convert the earnings-call
audio to a transcript instead of recording a gap.
- Audio source: the company's IR webcast replay page.
  Direct audio URLs are extracted per provider
  pattern (Q4, Notified, Intrado direct mp3 links);
  streaming-only (HLS) players with no extractable
  audio file stay gaps — recorded, not faked.
- Transcription runs on Workers AI Whisper (model id
  and limits — file size, duration, neuron cost per
  minute — verified live at build time, not assumed).
  Cost is the binding constraint: the free neuron
  budget cannot transcribe all 162 companies every
  quarter, so ASR is capped — on-demand when a
  briefing is requested and no text exists, plus
  small measured backfill batches. Measure the cost
  of one call first, then set the cap from the
  number, never from a guess.
- Guardrails, stricter than text transcripts:
  ASR text is stored with source_type "asr" and is
  searchable and usable for takeaways, tone, and
  Q&A themes — but it is NEVER passed to the Writer
  as story source, and no number from it can enter
  a briefing. Whisper mis-hears financial jargon and
  digits; a mis-heard number quoted as fact would
  break the verified-numbers rule. ASR text also
  carries no speaker labels (Whisper does not
  diarize), so Q&A attribution from ASR is weak
  and must be labelled as such.

## Why "every website" is scoped down
There is no single free transcript feed. Coverage is
Motley Fool for most large-caps plus IR pages for
the rest; "every website" would mean paywalls and
logins, which are not fetchable on the free tier,
plus audio that is only covered where Phase 2b
applies (extractable file, budget allows). The
honest claim is: every directory company's
transcript where a free text or transcribable
audio source exists, with gaps visible.

## Size and cost (D1 free tier: 5 GB, 100k writes/day)
Excerpts (~3 KB) for 162 companies × 4 quarters/yr
≈ 2 MB/yr. Full text (~20 KB) ≈ 13 MB/yr. Years of
archive fit without touching the free limits.

## Future uses (the reason to build it)
- Cross-quarter search: "what did management say
  about tariffs / pricing / headcount last quarter?"
- Guidance tracking: what they guided vs what they
  delivered, quarter by quarter.
- Q&A analysis: which questions got real answers
  and which got deflected.
- Grounding for takeaways and the fine-print
  section: management's own words, cited, not
  paraphrased from news.

## Open at build time
Log Worker name and D1 binding; whether Cron
Triggers on the free tier can run the backfill on a
schedule, or whether backfill stays a manual batch.

## Implementation notes (Batch 27 Phase 1, built Nov 4, 2026)
- Worker name settled: `mesh-transcript-log-proof`
  (TS, modelled on the search-log Worker, same
  observability block). D1 binding settled: the
  EXISTING `agent-mesh-briefings` database
  (5736d0f6-8cd1-4011-846c-043c6ea8d9ab) — no new
  database; the transcripts table sits beside the
  searches table. Endpoints: POST /log, GET
  /transcript?ticker=&quarter_end=, GET /recent
  (metadata only — excerpt_chars, no text), GET
  /stats (totals + by source_type). Table
  `transcripts` carries ticker, quarter_label,
  quarter_end, source_url, excerpt, source_type
  ('text' | 'asr'), fetched_at, with
  UNIQUE(ticker, quarter_end, source_url) so a
  Refresh re-log is a no-op (INSERT OR IGNORE).
  Excerpt cap 100,000 chars (v1 excerpts are
  ≤6,000; the headroom is for Phase 2 full text
  without a code change).
- Capture path: the Briefing gained
  `transcript_excerpt` + `quarter_end` (ISO),
  set by write_briefing from pack.transcript
  (excerpt ≤6,000 chars, whitespace-collapsed,
  as the transcript module already returns it).
  The Orchestrator POSTs it best-effort after
  every briefing completes — both the POST
  /tasks/send path and the SSE stream path
  (stream queues the briefing event first, then
  logs, so a slow log call never delays the
  render). 8s timeout, every failure swallowed,
  no-excerpt briefings not logged at all.
- Verified locally (wrangler dev --local, local
  D1): POST /log → ok; GET /transcript returns
  the full row; a duplicate POST leaves the total
  at 1 (dedupe proven); /recent is metadata-only;
  bad body → 400, missing row → 404. Tests:
  `tests/unit/test_transcript_archive.py` (3
  tests); full suite 200 passed, 1 skipped.
- Upload + live verification join the held bundle
  behind the Batch 20 verification report. At
  upload time the Workers Builds project
  `mesh-transcript-log-proof` still needs creating
  (build `cd cloudflare-proof/transcript-log &&
  npm ci`, deploy `cd cloudflare-proof/transcript-log
  && npx wrangler deploy`, Access OFF); the D1
  binding references the existing database, so no
  new DB work. Live checks then: run one briefing,
  confirm /recent shows the row and /transcript
  returns its excerpt.
- Phase 2 (backfill) and 2b (Whisper ASR) are NOT
  built in this batch — Phase 1 is the foundation
  they need (table + source_type + read endpoints).
  The open Cron-Triggers question stands: whether
  free-tier Cron Triggers can run the backfill, or
  it stays a manual batch. Whisper's model id,
  limits and neuron cost/minute are still to be
  verified live at 2b build time, not assumed.
