# ADR 058 — Batch 36: KPI extraction hardening (JSON repair + no settle on a first-model empty)

Date: 2026-11-05. Status: built + tested (262 passed, 1 skipped); upload + live verification pending.

## The failure

BROS (two full runs) and NVDA (one full run) all returned 0 KPIs and no
diagram, while the fine-print leg on the same pack returned 3 real items
when called directly. The direct KPI mode call on BROS's real pack also
returned 0 items in 64.6s, with 122ms CPU over a 63.6s wall — the leg
burned its wall on LLM attempts, not on fetching. Two defects in
`mesh/kpi.py` explain it:

1. **The chain settled on a clean-empty first reply.** `_settle_reply`
   returned settled for a reply that parsed cleanly to `{"kpis": []}`
   with no diagram, so the chain never tried the next model. The
   direct-call timing (fetch fast, then ~60s on one model) fits
   Workers AI timing out on the complex KPI+diagram prompt and a
   gateway model then returning a valid empty list. A small model
   often misses KPIs the next model finds; one empty verdict is not
   evidence the release has nothing.
2. **Strict JSON parsing with no repair.** `parse_kpi_response` did a
   single `json.loads` on the `{...}` span. A trailing comma before
   `}` or `]` — the most common small-model JSON slip — killed the
   whole reply as garbled, and the chain moved on with nothing.

## The fix

- `parse_kpi_response`: on `json.loads` failure, retry once with
  trailing commas before `}` or `]` stripped (`re.sub(r",\s*([}\]])", r"\1", span)`).
  That is the one repair that is unambiguous. Anything else garbled
  (unclosed strings, truncated output, single quotes) still fails
  cleanly. No other repair is attempted: guessing at structure risks
  inventing KPIs, which the validator exists to prevent.
- `_settle_reply(..., allow_empty=True)`: a clean-empty parse settles
  only when `allow_empty`. Both chains (`extract_kpis_async` and the
  sync twin `extract_kpis_sync`) now count successful model returns
  (`replies`); `allow_empty=replies > 1`, so only the SECOND model
  that returns successfully may settle on empty. A timeout or
  provider error does not count as an opinion — it increments
  nothing, so the next model still gets its first-opinion protection.
  A genuinely empty release now costs at most one extra model call.
- The diagram shares the call and the fix: the same reply carries
  both, so a diagram that the first model missed gets a second
  chance too.

## What did not change

- No timeout was changed (standing rule: the Writer chain timeouts
  stay as proven). The step deadline still bounds the worst case.
- The validator is untouched: `validate_kpis` (verbatim value check,
  kind normalization, cap 12) and `validate_diagram` (role/label
  rules, ≥2 nodes, ≥1 edge, exactly one company node) still drop
  anything ungrounded. Repair only fixes JSON syntax, never content.
- The `{"kpis": []}` contract is unchanged: a settled empty still
  returns `([], None)` and the section hides.

## Tests

- `test_parse_kpi_response_repairs_trailing_comma`: trailing commas
  before `}` and `]` parse; truncated output and single-quoted
  strings still fail.
- `test_extract_kpis_async_empty_list_needs_second_opinion` (replaces
  `test_extract_kpis_async_empty_list_stops_chain`, whose asserted
  behavior is intentionally changed): two models returning empty
  → both are called, result `([], None)`.
- `test_extract_kpis_async_first_empty_then_valid` and
  `test_extract_kpis_sync_first_empty_then_valid`: first model empty,
  second model returns KPIs → items returned, both models called.

## Open

- The fine-print leg returns 0 in the parallel full run but 3 items
  in isolation on the same pack. Leading hypothesis: the three
  concurrent mode calls' combined SEC fetch burst trips the rate
  limit. If Batch 36 does not clear the full-run KPI 0, the next
  step is staggering the mode calls or sharing fetched texts from
  the Orchestrator — not more chain tuning.
- The NVDA quarter-label wart (latest-run `quarter_end` is the
  Nasdaq month-end approximation 2026-07-31; the real fiscal end is
  2026-07-26) is a separate Scout issue, not touched here.
