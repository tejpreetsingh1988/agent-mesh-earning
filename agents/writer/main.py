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
from mesh.writer import write_briefing


def _handler(payload: dict) -> dict:
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
        return {"story_result": build_story(pack, analysis, api_key=api_key)}
    if mode == "kpi":
        # KPI step (Batch 22) + diagram spec (Batch 23, same call):
        # best-effort, after the Critic gate, never blocking.
        try:
            items, diagram, url = kpis_for_pack_sync(
                pack.ticker, pack.quarter_end.isoformat(), api_key=api_key)
            return {"kpi_result": {"items": items, "diagram": diagram, "source_url": url}}
        except Exception:
            return {"kpi_result": {"items": [], "diagram": None, "source_url": ""}}
    if mode == "fineprint":
        # Fine-print step (Batch 30): LLM-surfaced new/changed 10-Q
        # passages, best-effort like KPIs, never blocking.
        try:
            fp_items, fp_urls = fineprint_for_pack_sync(
                pack.ticker, pack.quarter_end.isoformat(), pack.quarter_label,
                api_key=api_key)
            return {"fine_print_result": {"items": fp_items, "source_urls": fp_urls}}
        except Exception:
            return {"fine_print_result": {"items": [], "source_urls": []}}
    # Full briefing (no mode): the KPI + fine-print steps run
    # best-effort, after the Critic gate, never blocking.
    # kpis_for_pack_sync already swallows its own errors; the
    # outer guard is belt-and-suspenders so a KPI failure can
    # never break a verified briefing.
    try:
        items, diagram, url = kpis_for_pack_sync(
            pack.ticker, pack.quarter_end.isoformat(), api_key=api_key)
        kpi_result = {"items": items, "diagram": diagram, "source_url": url}
    except Exception:
        kpi_result = None
    try:
        fp_items, fp_urls = fineprint_for_pack_sync(
            pack.ticker, pack.quarter_end.isoformat(), pack.quarter_label,
            api_key=api_key)
        fine_print_result = {"items": fp_items, "source_urls": fp_urls}
    except Exception:
        fine_print_result = None
    return write_briefing(pack, analysis, trace_id, kpi_result=kpi_result, fine_print_result=fine_print_result).model_dump(mode="json")


app = create_app("writer", handler=_handler)
