"""Analyst agent service — Day 3: Analysis from EvidencePack only.

Payload: {"evidence_pack": {...}} (or the pack itself as the payload)
Result: Analysis JSON. Analyst never calls a live data source.
"""
from mesh.agent_app import create_app
from mesh.analyst import analyse
from mesh.schemas import EvidencePack


def _handler(payload: dict) -> dict:
    pack_data = payload.get("evidence_pack") or payload.get("params", {}).get("evidence_pack") or payload
    pack = EvidencePack.model_validate(pack_data)
    return analyse(pack).model_dump(mode="json")


app = create_app("analyst", handler=_handler)


# Cloudflare Workers entrypoint. In the Worker runtime, `workers` is provided;
# locally it is absent, so the import is guarded and Default stays None there.
try:
    from workers import asgi as _worker_asgi
    Default = _worker_asgi.entrypoint(app)
except ImportError:  # local dev / tests only
    Default = None
