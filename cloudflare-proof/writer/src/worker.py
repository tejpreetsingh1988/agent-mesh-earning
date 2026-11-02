"""Writer agent service — Day 5: Briefing from approved Analysis only.

Payload: {"evidence_pack": {...}, "analysis": {...}, "trace_id": "..." (optional)}
Result: Briefing JSON. Writer adds no new numbers.
"""
import uuid

from mesh.agent_app import create_app
from mesh.schemas import Analysis, EvidencePack
from mesh.story_async import build_story_async
from mesh.worker_env import worker_env_value
from mesh.writer import write_briefing


async def _handler(payload: dict) -> dict:
    pack_data = payload.get("evidence_pack") or payload.get("params", {}).get("evidence_pack")
    analysis_data = payload.get("analysis") or payload.get("params", {}).get("analysis")
    if not pack_data or not analysis_data:
        raise ValueError("Writer task needs evidence_pack + analysis")
    pack = EvidencePack.model_validate(pack_data)
    analysis = Analysis.model_validate(analysis_data)
    trace_id = payload.get("trace_id") or str(uuid.uuid4())
    return write_briefing(pack, analysis, trace_id, story_result=await build_story_async(pack, analysis, api_key=worker_env_value("OPENROUTER_API_KEY"))).model_dump(mode="json")


app = create_app("writer", async_handler=_handler)


# Cloudflare Workers entrypoint. In the Worker runtime, `workers` is provided;
# locally it is absent, so the import is guarded and Default stays None there.
try:
    from workers import asgi as _worker_asgi
    Default = _worker_asgi.entrypoint(app)
except ImportError:  # local dev / tests only
    Default = None
