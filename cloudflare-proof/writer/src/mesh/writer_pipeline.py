"""Writer pipeline (async, cloud path): run the three Writer
steps concurrently with a per-chain deadline.

Why this exists (Nov 5, 2026): the Writer used to run its three
LLM chains SEQUENTIALLY — KPI extraction, then fine-print, then
the story — each trying up to 5 model attempts at 60s apiece
(Workers AI 60s + 3 gateway models x 60s + 3 OpenRouter x 60s
= 420s worst case per chain). For GOOGL's Q3 2026 briefing the
Writer was still running at 299s; the Orchestrator's stream
request was then canceled by the Cloudflare runtime as "hung"
at ~311s wall with no error event and no briefing — the client
saw the stream simply end. The Writer itself was never
CPU-killed (946ms CPU); it was just too slow.

The fix: the three chains are independent (KPIs are not in the
story prompt; fine print is its own section), so they run
concurrently under asyncio.gather, each under its own deadline.
Worst case the Writer now takes one deadline (180s), not three
chain-times, and a timed-out chain falls back to its designed
hiding result (deterministic story / no KPIs / no fine print)
instead of killing the briefing.

The Docker/sync path (agents/writer/main.py) stays sequential:
it is not the live path, and its blocking calls cannot await.
This module is the async twin used by the Writer proof, wired
in by scripts/sync-worker-proof.py::_writer().
"""
import asyncio

from .fineprint import fineprint_for_pack_async
from .kpi import kpis_for_pack_async
from .llm import deterministic_story
from .story_async import build_story_async

# Per-chain deadline. Worst-case Writer wall time is one
# deadline (the chains run concurrently), keeping a full
# stream run (~15s pipeline + this) well under the ~300s edge
# limit that killed the GOOGL stream. A story that legitimately
# needs longer falls back to the deterministic story rather
# than hanging the briefing.
WRITER_CHAIN_TIMEOUT_S = 180


async def _with_deadline(coro, default):
    """Await coro, or return default on timeout or any error.
    A chain failure must never break a verified briefing."""
    try:
        return await asyncio.wait_for(coro, timeout=WRITER_CHAIN_TIMEOUT_S)
    except Exception:
        return default


async def run_writer_steps_async(pack, analysis, api_key: str = "", ai=None):
    """(story_dict, (kpi_items, kpi_diagram, kpi_url),
    (fp_items, fp_urls)) — the three Writer steps, run
    concurrently. Each step keeps its own best-effort contract:
    the KPI and fine-print steps return empty on failure (the
    section hides), and the story falls back to the
    deterministic story."""
    story_default = {"story": deterministic_story(pack, analysis),
                     "model": "deterministic (Writer chain timed out)",
                     "tokens_in": None, "tokens_out": None, "latency_s": None}
    story, kpi_res, fp_res = await asyncio.gather(
        _with_deadline(
            build_story_async(pack, analysis, api_key=api_key, ai=ai),
            story_default),
        _with_deadline(
            kpis_for_pack_async(pack.ticker, pack.quarter_end.isoformat(),
                                ai=ai, api_key=api_key),
            ([], None, "")),
        _with_deadline(
            fineprint_for_pack_async(pack.ticker, pack.quarter_end.isoformat(),
                                     pack.quarter_label, ai=ai, api_key=api_key),
            ([], [])),
    )
    return story, kpi_res, fp_res
