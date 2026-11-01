"""Agent Cards — one per agent, served at /.well-known/agent.json.
Orchestrator discovers agents by reading these at startup (Day 5).
"""
def _card(name, desc, skill_id, skill_name, skill_desc):
    port = {"orchestrator": 8000, "scout": 8001, "analyst": 8002, "critic": 8003, "writer": 8004}[name]
    return {
        "name": f"earnings-{name}",
        "description": desc,
        "url": f"http://{name}: {port}/".replace(" ", ""),
        "version": "0.1.0-day1",
        "capabilities": {"streaming": False},
        "skills": [{"id": skill_id, "name": skill_name, "description": skill_desc,
                    "inputModes": ["application/json"], "outputModes": ["application/json"]}],
    }

CARDS = {
    "orchestrator": _card("orchestrator", "Owns the user task, routes Scout->Analyst->Critic->Writer, enforces timeouts and the Critic loop.", "run_briefing", "Run earnings briefing", "Given user text, return a verified Briefing."),
    "scout": _card("scout", "Collects earnings evidence from filings, market data, and news via MCP. Returns cited facts only, no interpretation.", "collect_evidence", "Collect earnings evidence", "Given a ticker, return an EvidencePack for its most recent reported quarter."),
    "analyst": _card("analyst", "Computes beat/miss, growth, and margins from the EvidencePack only, with derivations for every claim.", "analyse", "Analyse evidence", "Given an EvidencePack, return an Analysis."),
    "critic": _card("critic", "Independently re-queries MCP tools and checks arithmetic, labels, beat/miss, and omissions. Returns PASS/FAIL.", "critique", "Critique analysis", "Given EvidencePack + Analysis, return a Critique."),
    "writer": _card("writer", "Writes the briefing prose from the approved Analysis only. Introduces no new numbers.", "write", "Write briefing", "Given an approved Analysis, return a Briefing."),
}
