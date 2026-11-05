"""Writer agent service — Day 5: Briefing from approved Analysis only.

Payload: {"evidence_pack": {...}, "analysis": {...}, "trace_id": "..." (optional)}
Result: Briefing JSON. Writer adds no new numbers.
"""
import os
import uuid

from mesh.agent_app import create_app
from mesh.fineprint import fineprint_for_pack_sync
from mesh.kpi import kpis_for_pack_sync
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
    # KPI step (Batch 22) + diagram spec (Batch 23, same call):
    # best-effort, after the Critic gate, never blocking.
    # kpis_for_pack_sync already swallows its own errors; the
    # outer guard is belt-and-suspenders so a KPI failure can
    # never break a verified briefing.
    try:
        items, diagram, url = kpis_for_pack_sync(
            pack.ticker, pack.quarter_end.isoformat(),
            api_key=os.environ.get("OPENROUTER_API_KEY", ""))
        kpi_result = {"items": items, "diagram": diagram, "source_url": url}
    except Exception:
        kpi_result = None
    # Fine-print step (Batch 30): LLM-surfaced new/changed 10-Q
    # passages, best-effort like KPIs, never blocking.
    try:
        fp_items, fp_urls = fineprint_for_pack_sync(
            pack.ticker, pack.quarter_end.isoformat(), pack.quarter_label,
            api_key=os.environ.get("OPENROUTER_API_KEY", ""))
        fine_print_result = {"items": fp_items, "source_urls": fp_urls}
    except Exception:
        fine_print_result = None
    return write_briefing(pack, analysis, trace_id, kpi_result=kpi_result, fine_print_result=fine_print_result).model_dump(mode="json")


app = create_app("writer", handler=_handler)
