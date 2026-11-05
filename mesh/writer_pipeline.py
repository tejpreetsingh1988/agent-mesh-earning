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

Batch 34 (Nov 5, 2026): the three steps are ALSO callable
individually (run_story_step_async / run_kpi_step_async /
run_fineprint_step_async). The single-invocation Writer kept
dying at exactly 2,010ms CPU on GOOGL — the three chains'
parse/diff/validate together exceed the Workers Free CPU
budget in Pyodide (the NVDA success already burned 1,445ms
with KPIs skipped and fine print empty; local CPython profiles
the framework at ~0ms and the fine-print parse at ~0.30s, so
the multiplier is Pyodide itself). Wall-time parallelism
cannot fix a CPU budget: the fix is to split the CPU across
invocations. The Orchestrator now calls the Writer three
times in parallel, one mode per call (mode=story / mode=kpi /
mode=fineprint), each with its own 2,000ms budget, and
assembles the Briefing itself. run_writer_steps_async (the
gather) stays for the no-mode path and the Docker twin.
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


async def run_story_step_async(pack, analysis, api_key: str = "", ai=None):
    """The story step alone: the LLM story (or the deterministic
    story on timeout/failure). Never raises — a timed-out chain
    returns the deterministic story, never a broken briefing."""
    story_default = {"story": deterministic_story(pack, analysis),
                     "model": "deterministic (Writer chain timed out)",
                     "tokens_in": None, "tokens_out": None, "latency_s": None}
    return await _with_deadline(
        build_story_async(pack, analysis, api_key=api_key, ai=ai),
        story_default)


async def run_kpi_step_async(pack, api_key: str = "", ai=None):
    """The KPI + diagram step alone, as a kpi_result dict.
    Never raises — a failure returns the hiding result. The
    Batch 38 debug dict rides along (dropped by write_briefing;
    visible on the direct mode call) so a 0 can be diagnosed."""
    debug: dict = {}
    items, diagram, url = await _with_deadline(
        kpis_for_pack_async(pack.ticker, pack.quarter_end.isoformat(),
                            ai=ai, api_key=api_key, debug=debug),
        ([], None, ""))
    debug.setdefault("settled_on", "incomplete")
    return {"items": items, "diagram": diagram, "source_url": url, "debug": debug}


async def run_fineprint_step_async(pack, api_key: str = "", ai=None):
    """The fine-print step alone, as a fine_print_result dict.
    Never raises — a failure returns the hiding result."""
    items, urls = await _with_deadline(
        fineprint_for_pack_async(pack.ticker, pack.quarter_end.isoformat(),
                                 pack.quarter_label, ai=ai, api_key=api_key),
        ([], []))
    return {"items": items, "source_urls": urls}


async def run_writer_steps_async(pack, analysis, api_key: str = "", ai=None):
    """(story_dict, (kpi_items, kpi_diagram, kpi_url),
    (fp_items, fp_urls)) — the three Writer steps, run
    concurrently. Each step keeps its own best-effort contract:
    the KPI and fine-print steps return empty on failure (the
    section hides), and the story falls back to the
    deterministic story."""
    story, kpi_result, fp_result = await asyncio.gather(
        run_story_step_async(pack, analysis, api_key=api_key, ai=ai),
        run_kpi_step_async(pack, api_key=api_key, ai=ai),
        run_fineprint_step_async(pack, api_key=api_key, ai=ai),
    )
    return story, (kpi_result["items"], kpi_result["diagram"],
                   kpi_result["source_url"]), (fp_result["items"],
                                               fp_result["source_urls"])
