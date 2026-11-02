"""Critic agent service — Day 4: independent re-check via MCP.

Payload: {"evidence_pack": {...}, "analysis": {...}}
Result: Critique JSON (PASS/FAIL + issues + rechecked facts).
"""
from mesh.agent_app import create_app
from mesh.critic_async import critique_async
from mesh.async_tools import async_direct_call
from mesh.schemas import Analysis, EvidencePack


async def _handler(payload: dict) -> dict:
    pack_data = payload.get("evidence_pack") or payload.get("params", {}).get("evidence_pack")
    analysis_data = payload.get("analysis") or payload.get("params", {}).get("analysis")
    if not pack_data or not analysis_data:
        raise ValueError("Critic task needs evidence_pack + analysis")
    pack = EvidencePack.model_validate(pack_data)
    analysis = Analysis.model_validate(analysis_data)
    return (await critique_async(pack, analysis, mcp_call=async_direct_call)).model_dump(mode="json")


app = create_app("critic", async_handler=_handler)


# Cloudflare Workers entrypoint. In the Worker runtime, `workers` is provided;
# locally it is absent, so the import is guarded and Default stays None there.
try:
    from workers import asgi as _worker_asgi
    Default = _worker_asgi.entrypoint(app)
except ImportError:  # local dev / tests only
    Default = None
