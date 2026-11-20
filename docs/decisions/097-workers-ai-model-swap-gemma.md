# Workers AI model swap — decision note (Nov 19, 2026)

## Question
Llama 3.1 8B (`@cf/meta/llama-3.1-8b-instruct-fp8`) stops responding Fri Nov 20, 2026
(requests fail with a 410). Which replacement keeps the briefings on Workers AI
inside the free 10,000-neuron/day allowance: `gemma-4-26b-a4b-it` or `qwen3.8-27b`?

## Answer: gemma — verified, with the numbers
Checked Nov 19, 2026 against Cloudflare's own pricing page
(developers.cloudflare.com/workers-ai/platform/pricing/) and its per-model
figures as republished by independent pricing trackers (all consistent):

- Free allowance: **10,000 Neurons/day, reset 00:00 UTC**, on both Workers Free
  and Workers Paid. Over that, Free stops (error 3036); Paid bills
  $0.011 per 1,000 Neurons.
- **Gemma 4 26B** `@cf/google/gemma-4-26b-a4b-it`: $0.10 / 1M input tokens,
  $0.30 / 1M output tokens = **9,091 / 27,273 neurons per 1M tokens**.
  Not one of the 7 paid-only models (Kimi K2.6/K2.7, GLM 5.2/5.3/5.3-flash,
  DeepSeek V4 Flash/Pro) — it is open to the Free plan.
- **Qwen3.8 27B** `@cf/qwen/qwen3.8-27b`: $0.45 / 1M in, $3.20 / 1M out =
  **40,909 / 290,909 neurons per 1M tokens**. Also free-eligible, but
  ~4.5x gemma on input and **~10.7x on output**.

## Neuron math per briefing (estimate, labelled)
Three Workers AI legs per briefing — story (`mesh/story_async.py`),
KPI two-phase (`mesh/kpi.py`), fine-print (`mesh/fineprint.py`) — all via
`mesh/worker_ai.py`, which caps the story call at `max_tokens: 1800`.

| leg | gemma (worst case) | qwen (same workload) |
|---|---|---|
| Story (~4k in, 1.8k out) | ~36 + ~49 = ~85 | ~164 + ~524 = ~688 |
| KPI, two phases (~2k in, ~1k out each) | ~90 | ~746 |
| Fine-print (short) | ~30 | ~300 |
| **Per briefing** | **~200 neurons** | **~1,700 neurons** |
| **Briefings per free day** | **~50** | **~5–6** |

For scale: the Llama docstring in `worker_ai.py` records ~490 replies/day
(~20 neurons each) for the story-sized call. Gemma is ~4x pricier per call
than Llama, qwen ~34x. A realistic sync day is a handful of briefings, so
gemma has roughly 10–50x headroom; qwen would exhaust the allowance on a
normal sync day and a single long story call eats ~700 neurons. **Qwen is
impractical on the free tier for this workload. Gemma is the pick.**

Caveat: these are Cloudflare's published per-token equivalents, not measured
usage. Real token counts are recorded by `call_workers_ai` (tokens_in /
tokens_out), so the live proof briefing after the swap shows the true
neuron cost — check it before calling the swap done.

## Update (Nov 20, 2026) — interim pick: Llama 3.3 70B, applied
Tej chose Llama 3.3 70B ("for now") over gemma, to stay on a Llama model.
Applied Nov 20, 2026:
- `WORKERS_AI_MODEL = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"` in both
  files (verified against the current catalog page,
  developers.cloudflare.com/workers-ai/models/llama-3.3-70b-instruct-fp8-fast/;
  context window 24,000 tokens). Proof copy regenerated via
  `scripts/sync-worker-proof.py`; both copies identical.
- Cost: $0.293/M in, $2.253/M out = 26,668 / 204,805 neurons per 1M tokens.
  Per-briefing estimate (same token assumptions as above): story ~476 +
  KPI ~516 + fine-print ~88 ≈ **~1,080 neurons → ~9 briefings/day** on the
  free allowance. ~5x gemma's cost; a normal sync day (a handful of
  briefings) still fits, but a heavy day could exhaust it — check the live
  proof's measured usage before calling the swap done.
- **Gemma remains the recommended long-term pick.** If Llama 3.3's measured
  cost bites, swap to gemma with the same one-line change.
- Live proof still pending Tej's wrangler redeploy (no auth on this VM);
  after deploy, probe the live site for a Workers AI `story_model` and the
  measured tokens_in/tokens_out.

## Exact change for the gemma alternative (not applied — superseded for now by the Llama 3.3 interim pick above)
One line, two files (the repo copy and the deployed proof copy carry the
same constant):
- `mesh/worker_ai.py:54`: `WORKERS_AI_MODEL = "@cf/google/gemma-4-26b-a4b-it"`
- `cloudflare-proof/writer/src/mesh/worker_ai.py:54`: same
- Also update the "Model choice" docstring paragraph in both files (it
  currently justifies the Llama choice and the ~490/day figure).
- Tests use the `WORKERS_AI_MODEL` constant, so no test change is needed;
  run the full suite (367 tests) before redeploy.
- Redeploy is Tej's wrangler step (`wrangler login` + deploy in the
  MCP server folder / Workers), then live-proof one full briefing and
  confirm the `story_model` label reads Workers AI/gemma and the neuron
  usage matches the estimate above. Fallback chain (OpenRouter, then
  deterministic story) is unchanged — a gemma failure never breaks a briefing.
