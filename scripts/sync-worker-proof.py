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
                        "from mesh.fineprint import fineprint_for_pack_async\nfrom mesh.kpi import kpis_for_pack_async\nfrom mesh.story_async import build_story_async\nfrom mesh.worker_env import ai_binding, worker_env_value\nfrom mesh.writer import write_briefing")
    base = base.replace("def _handler(payload: dict) -> dict:",
                        "async def _handler(payload: dict) -> dict:")
    # The key is passed explicitly from the Worker env object:
    # dashboard secrets are NOT visible in os.environ in a Python
    # Worker, so build_story_async's os.environ fallback alone
    # always yields the deterministic story in the cloud (see
    # mesh/worker_env.py and docs/decisions/011-worker-env.md).
    # Workers AI first (binding, no key), then the OpenRouter
    # chain through AI Gateway via the binding (dynamic routes,
    # gateway supplies the stored key — see
    # mesh/gateway_binding.py, ADR 016 addendum), then direct
    # OpenRouter with the key header. ai_binding() returns None
    # locally and in Workers without the ai binding declared, so
    # the direct path is unchanged there (see mesh/worker_ai.py,
    # ADR 015). The GATEWAY_OPENROUTER_URL variable is no longer
    # read: the first gateway attempt (HTTPS, no header) 401'd
    # under Authenticated Gateway, and the binding replaces it.
    # Batch 22: the sync handler's KPI call (urllib) cannot run in
    # a Worker, so the proof replaces it with the async KPI step
    # on the same ai/key context as the story call. The KPI step
    # is best-effort inside kpis_for_pack_async; it never raises
    # to the briefing.
    base = base.replace(
        "    # KPI step (Batch 22) + diagram spec (Batch 23, same call):\n"
        "    # best-effort, after the Critic gate, never blocking.\n"
        "    # kpis_for_pack_sync already swallows its own errors; the\n"
        "    # outer guard is belt-and-suspenders so a KPI failure can\n"
        "    # never break a verified briefing.\n"
        "    try:\n"
        "        items, diagram, url = kpis_for_pack_sync(\n"
        "            pack.ticker, pack.quarter_end.isoformat(),\n"
        "            api_key=os.environ.get(\"OPENROUTER_API_KEY\", \"\"))\n"
        "        kpi_result = {\"items\": items, \"diagram\": diagram, \"source_url\": url}\n"
        "    except Exception:\n"
        "        kpi_result = None\n"
        "    # Fine-print step (Batch 30): LLM-surfaced new/changed 10-Q\n"
        "    # passages, best-effort like KPIs, never blocking.\n"
        "    try:\n"
        "        fp_items, fp_urls = fineprint_for_pack_sync(\n"
        "            pack.ticker, pack.quarter_end.isoformat(), pack.quarter_label,\n"
        "            api_key=os.environ.get(\"OPENROUTER_API_KEY\", \"\"))\n"
        "        fine_print_result = {\"items\": fp_items, \"source_urls\": fp_urls}\n"
        "    except Exception:\n"
        "        fine_print_result = None\n"
        "    return write_briefing(pack, analysis, trace_id, kpi_result=kpi_result, fine_print_result=fine_print_result).model_dump(mode=\"json\")",
        "    story = await build_story_async(pack, analysis, api_key=worker_env_value(\"OPENROUTER_API_KEY\"), ai=ai_binding())\n"
        "    kpi_items, kpi_diagram, kpi_url = await kpis_for_pack_async(pack.ticker, pack.quarter_end.isoformat(), ai=ai_binding(), api_key=worker_env_value(\"OPENROUTER_API_KEY\"))\n"
        "    fp_items, fp_urls = await fineprint_for_pack_async(pack.ticker, pack.quarter_end.isoformat(), pack.quarter_label, ai=ai_binding(), api_key=worker_env_value(\"OPENROUTER_API_KEY\"))\n"
        "    return write_briefing(pack, analysis, trace_id, story_result=story, kpi_result={\"items\": kpi_items, \"diagram\": kpi_diagram, \"source_url\": kpi_url}, fine_print_result={\"items\": fp_items, \"source_urls\": fp_urls}).model_dump(mode=\"json\")")
    base = base.replace('app = create_app("writer", handler=_handler)',
                        'app = create_app("writer", async_handler=_handler)')
    _sync("writer",
          ["__init__.py", "schemas.py", "writer.py", "llm.py", "story_async.py",
           "worker_env.py", "worker_ai.py", "gateway_binding.py",
           "agent_app.py", "cards.py", "auth.py", "worker_http.py",
           "kpi.py", "fineprint.py", "edgar.py"],
          base + ENTRYPOINT)


def _orchestrator() -> None:
    base = (ROOT / "apps" / "orchestrator" / "worker_main.py").read_text()
    _sync("orchestrator",
          ["__init__.py", "schemas.py", "orchestrator.py", "orchestrator_async.py",
           "writer.py", "llm.py", "agent_app.py", "cards.py", "auth.py", "worker_http.py",
           "ownership.py", "history.py", "edgar.py",
           # history.py -> async_tools.py, whose closure is
           # stdlib-only (same set the critic proof vendors):
           "async_tools.py", "edgar_facts.py", "consensus.py", "transcript.py",
           "market.py"],
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
