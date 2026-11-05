"""Writer agent service — Day 5: Briefing from approved Analysis only.

Payload: {"evidence_pack": {...}, "analysis": {...}, "trace_id": "..." (optional)}
Result: Briefing JSON. Writer adds no new numbers.

Batch 34 (Nov 5, 2026): the payload may carry "mode":
"story", "kpi" or "fineprint" — one Writer step only, as
{"story_result": ...} / {"kpi_result": ...} /
{"fine_print_result": ...}. The Orchestrator calls the Writer
three times in parallel, one mode per call, because a single
Writer invocation kept dying at exactly 2,010ms CPU on GOOGL
(the three chains' parse/diff/validate together exceed the
Workers Free CPU budget in Pyodide). Each mode call gets its
own 2,000ms budget; the Orchestrator assembles the Briefing.
No mode (the default) returns the full briefing as before.
"""
import os
import uuid

from mesh.agent_app import create_app
from mesh.fineprint import fineprint_for_pack_sync
from mesh.kpi import kpis_for_pack_sync
from mesh.llm import build_story
from mesh.schemas import Analysis, EvidencePack
from mesh.writer_pipeline import run_writer_steps_async, run_story_step_async, run_kpi_step_async, run_fineprint_step_async
from mesh.worker_env import ai_binding, worker_env_value
from mesh.writer import write_briefing


async def _handler(payload: dict) -> dict:
    pack_data = payload.get("evidence_pack") or payload.get("params", {}).get("evidence_pack")
    analysis_data = payload.get("analysis") or payload.get("params", {}).get("analysis")
    if not pack_data or not analysis_data:
        raise ValueError("Writer task needs evidence_pack + analysis")
    pack = EvidencePack.model_validate(pack_data)
    analysis = Analysis.model_validate(analysis_data)
    trace_id = payload.get("trace_id") or str(uuid.uuid4())
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    mode = payload.get("mode")
    if mode == "story":
        return {"story_result": await run_story_step_async(pack, analysis, api_key=worker_env_value("OPENROUTER_API_KEY"), ai=ai_binding())}
    if mode == "kpi":
        return {"kpi_result": await run_kpi_step_async(pack, api_key=worker_env_value("OPENROUTER_API_KEY"), ai=ai_binding())}
    if mode == "fineprint":
        return {"fine_print_result": await run_fineprint_step_async(pack, api_key=worker_env_value("OPENROUTER_API_KEY"), ai=ai_binding())}
    story, (kpi_items, kpi_diagram, kpi_url), (fp_items, fp_urls) = await run_writer_steps_async(pack, analysis, api_key=worker_env_value("OPENROUTER_API_KEY"), ai=ai_binding())
    return write_briefing(pack, analysis, trace_id, story_result=story, kpi_result={"items": kpi_items, "diagram": kpi_diagram, "source_url": kpi_url}, fine_print_result={"items": fp_items, "source_urls": fp_urls}).model_dump(mode="json")


app = create_app("writer", async_handler=_handler)


# Cloudflare Workers entrypoint. In the Worker runtime, `workers` is provided;
# locally it is absent, so the import is guarded and Default stays None there.
try:
    from workers import asgi as _worker_asgi
    Default = _worker_asgi.entrypoint(app)
except ImportError:  # local dev / tests only
    Default = None
