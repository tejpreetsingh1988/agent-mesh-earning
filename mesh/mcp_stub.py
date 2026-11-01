"""Day 1 MCP stub: lists the tools each server will implement on Day 2.
Day 2 replaces this with FastMCP (Streamable HTTP) + live EDGAR / price calls.
"""
from fastapi import FastAPI
from fastapi.responses import JSONResponse

TOOLS = {
    "filings": ["get_company_facts", "get_latest_earnings_filing", "get_filing_text", "get_transcript_excerpt", "list_recent_filings"],
    "market": ["get_price_reaction", "get_quarterly_history", "get_company_profile"],
    "estimates_news": ["get_consensus_estimates", "get_earnings_calendar", "get_recent_news"],
}

def create_mcp_app(server: str) -> FastAPI:
    app = FastAPI(title=f"{server}-mcp")

    @app.get("/health")
    def health():
        return {"status": "ok", "mcp_server": server, "version": "0.1.0-day1"}

    @app.get("/tools")
    def tools():
        return {"server": server, "tools": TOOLS[server],
                "note": "Day 1 stub — live tools land Day 2 via FastMCP."}

    @app.post("/tools/call")
    def call(payload: dict):
        return JSONResponse(status_code=501, content={"error": "Day 1 stub: MCP tool not yet implemented (Day 2)."})
    return app
