"""Regenerate cloudflare-proof/{analyst,scout,critic,writer,orchestrator}/src
from the repo's mesh/ modules.

Each Worker project must be self-contained (its root is what pywrangler
bundles), so it vendors the modules it needs. Repo root mesh/ is the
source of truth; never hand-edit a copy.

Analyst: five pure modules, no live data calls.
Scout v2: the same core plus the filing/market/consensus/transcript
modules and mesh/async_tools.py, so it can call MCP tools
in-process instead of over HTTP (a Worker has no sibling services)
AND asynchronously — v1's sync direct_call died in-Worker because
Python Workers cannot do synchronous urllib (see
mesh/worker_http.py). Scout's worker.py is derived from
agents/scout/main.py with the handler made async and the client
swapped from make_client() to async_direct_call.
"""
import pathlib
import shutil

ROOT = pathlib.Path(__file__).resolve().parent.parent

ENTRYPOINT = """

# Cloudflare Workers entrypoint. In the Worker runtime, `workers` is provided;
# locally it is absent, so the import is guarded and Default stays None there.
try:
    from workers import asgi as _worker_asgi
    Default = _worker_asgi.entrypoint(app)
except ImportError:  # local dev / tests only
    Default = None
"""


def _sync(name: str, files: list[str], worker_src: str) -> None:
    dest = ROOT / "cloudflare-proof" / name / "src"
    dest.mkdir(parents=True, exist_ok=True)
    mesh = dest / "mesh"
    mesh.mkdir(exist_ok=True)
    for f in files:
        shutil.copyfile(ROOT / "mesh" / f, mesh / f)
    (dest / "worker.py").write_text(worker_src)
    print(f"synced {dest}")


def _analyst() -> None:
    base = (ROOT / "agents" / "analyst" / "main.py").read_text()
    _sync("analyst",
          ["__init__.py", "schemas.py", "analyst.py", "agent_app.py", "cards.py", "auth.py"],
          base + ENTRYPOINT)


def _critic() -> None:
    base = (ROOT / "agents" / "critic" / "main.py").read_text()
    base = base.replace("from mesh.mcp_client import make_client",
                        "from mesh.async_tools import async_direct_call")
    base = base.replace("from mesh.critic import critique",
                        "from mesh.critic_async import critique_async")
    base = base.replace("def _handler(payload: dict) -> dict:",
                        "async def _handler(payload: dict) -> dict:")
    base = base.replace("return critique(pack, analysis, mcp_call=make_client()).model_dump(mode=\"json\")",
                        "return (await critique_async(pack, analysis, mcp_call=async_direct_call)).model_dump(mode=\"json\")")
    base = base.replace('app = create_app("critic", handler=_handler)',
                        'app = create_app("critic", async_handler=_handler)')
    _sync("critic",
          ["__init__.py", "schemas.py", "analyst.py", "critic.py", "critic_async.py",
           "agent_app.py", "cards.py", "auth.py",
           "edgar.py", "edgar_facts.py", "consensus.py", "news.py", "transcript.py",
           "market.py", "worker_http.py", "async_tools.py"],
          base + ENTRYPOINT)


def _writer() -> None:
    base = (ROOT / "agents" / "writer" / "main.py").read_text()
    base = base.replace("from mesh.writer import write_briefing",
                        "from mesh.story_async import build_story_async\nfrom mesh.worker_env import ai_binding, worker_env_value\nfrom mesh.writer import write_briefing")
    base = base.replace("def _handler(payload: dict) -> dict:",
                        "async def _handler(payload: dict) -> dict:")
    # The key is passed explicitly from the Worker env object:
    # dashboard secrets are NOT visible in os.environ in a Python
    # Worker, so build_story_async's os.environ fallback alone
    # always yields the deterministic story in the cloud (see
    # mesh/worker_env.py and docs/decisions/011-worker-env.md).
    # Workers AI first (binding, no key), OpenRouter as fallback:
    # ai_binding() returns None locally and in Workers without
    # the ai binding declared, so the OpenRouter path is
    # unchanged there (see mesh/worker_ai.py, ADR 015).
    # The OpenRouter fallback is routed via AI Gateway when the
    # GATEWAY_OPENROUTER_URL Worker variable is set (BYOK key,
    # analytics, caching); otherwise it goes direct with the
    # key header (see ADR 016). The variable is set in the
    # dashboard, never baked into the repo.
    base = base.replace("return write_briefing(pack, analysis, trace_id).model_dump(mode=\"json\")",
                        "return write_briefing(pack, analysis, trace_id, story_result=await build_story_async(pack, analysis, api_key=worker_env_value(\"OPENROUTER_API_KEY\"), ai=ai_binding(), gateway_url=worker_env_value(\"GATEWAY_OPENROUTER_URL\"))).model_dump(mode=\"json\")")
    base = base.replace('app = create_app("writer", handler=_handler)',
                        'app = create_app("writer", async_handler=_handler)')
    _sync("writer",
          ["__init__.py", "schemas.py", "writer.py", "llm.py", "story_async.py",
           "worker_env.py", "worker_ai.py",
           "agent_app.py", "cards.py", "auth.py", "worker_http.py"],
          base + ENTRYPOINT)


def _orchestrator() -> None:
    base = (ROOT / "apps" / "orchestrator" / "worker_main.py").read_text()
    _sync("orchestrator",
          ["__init__.py", "schemas.py", "orchestrator.py", "orchestrator_async.py",
           "writer.py", "llm.py", "agent_app.py", "cards.py", "auth.py", "worker_http.py"],
          base + ENTRYPOINT)


def _scout() -> None:
    base = (ROOT / "agents" / "scout" / "main.py").read_text()
    base = base.replace("from mesh.mcp_client import make_client",
                        "from mesh.async_tools import async_direct_call")
    base = base.replace("from mesh.scout import collect_evidence",
                        "from mesh.scout_async import collect_evidence_async")
    base = base.replace("def _handler(payload: dict) -> dict:",
                        "async def _handler(payload: dict) -> dict:")
    base = base.replace("pack = collect_evidence(ticker, make_client(), quarter=quarter)",
                        "pack = await collect_evidence_async(ticker, async_direct_call, quarter=quarter)")
    base = base.replace('app = create_app("scout", handler=_handler)',
                        'app = create_app("scout", async_handler=_handler)')
    base = base.replace(
        "MCP URLs come from env (see\nmesh/mcp_client.py); in Docker Compose they are the service names.",
        "Tools run in-process via mesh/async_tools.py — a Worker has\nno sibling MCP services to call over HTTP, and its fetch is\nasync (pyfetch) because Workers cannot do sync urllib.")
    _sync("scout",
          ["__init__.py", "schemas.py", "scout.py", "scout_async.py", "agent_app.py", "cards.py", "auth.py",
           "edgar.py", "edgar_facts.py", "consensus.py", "news.py", "transcript.py",
           "market.py", "direct_client.py", "worker_http.py", "async_tools.py"],
          base + ENTRYPOINT)


if __name__ == "__main__":
    _analyst()
    _scout()
    _critic()
    _writer()
    _orchestrator()
