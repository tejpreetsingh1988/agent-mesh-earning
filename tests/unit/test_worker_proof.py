"""Cloudflare Worker proof: the vendored Analyst copy must behave exactly
like the repo's Analyst service (same Analysis for the same EvidencePack).
The Worker runtime itself (`workers` module) is absent locally, so Default
is None here; the real Worker deploy is the remaining proof step.

Import isolation note: the Scout proof test loads a different module
also named `worker` in this same pytest process, so this file loads
the Analyst proof in a swap: temporarily replace the cached `mesh`
tree with the Analyst proof's vendored copy, import its `worker`,
then restore the cache and the path. The proof app object keeps its
vendored modules, so TestClient still exercises the proof code
after the restore.
"""
import json
import pathlib
import sys

from fastapi.testclient import TestClient

from agents.analyst.main import app as repo_app
from mesh.schemas import EvidencePack

_ANALYST_SRC = pathlib.Path(__file__).parents[2] / "cloudflare-proof" / "analyst" / "src"

_saved_mesh = {k: v for k, v in sys.modules.items() if k == "mesh" or k.startswith("mesh.")}
_saved_worker = sys.modules.pop("worker", None)
for _k in list(_saved_mesh):
    del sys.modules[_k]
sys.path.insert(0, str(_ANALYST_SRC))
import worker as proof  # noqa: E402  (path setup above)
for _k in [k for k in sys.modules if k == "mesh" or k.startswith("mesh.")]:
    del sys.modules[_k]
sys.modules.update(_saved_mesh)
if _saved_worker is not None:
    sys.modules["worker"] = _saved_worker
sys.path.remove(str(_ANALYST_SRC))


def _pack():
    path = pathlib.Path(__file__).parents[1] / "fixtures" / "googl_q3_2026.json"
    return json.loads(path.read_text())


def test_proof_analyst_matches_repo():
    pack = _pack()
    EvidencePack.model_validate(pack)  # fixture is a valid pack
    repo = TestClient(repo_app).post("/tasks/send", json={"evidence_pack": pack}).json()
    mine = TestClient(proof.app).post("/tasks/send", json={"evidence_pack": pack}).json()
    assert repo["state"] == mine["state"] == "completed"
    assert repo["result"] == mine["result"]


def test_proof_health_and_card():
    client = TestClient(proof.app)
    assert client.get("/health").json()["agent"] == "analyst"
    assert client.get("/.well-known/agent.json").json()["name"] == "earnings-analyst"


def test_worker_entrypoint_absent_locally():
    # `workers` exists only in the Cloudflare runtime.
    assert proof.Default is None
