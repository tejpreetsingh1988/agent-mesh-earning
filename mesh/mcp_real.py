"""Day 2 MCP servers as HTTP JSON services.
Same endpoints as Day 1 (/health, /tools, /tools/call), but /tools/call
now actually executes the tool. This keeps Docker Compose working unchanged
on Windows. A strict FastMCP Streamable-HTTP transport is the Day 2b
follow-up (see README) — the tool functions in mesh/edgar.py, mesh/market.py
and mesh/news.py are transport-agnostic and will be reused there unchanged.
"""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from mesh.auth import is_authorized

def create_mcp_app(server: str, tools: dict) -> FastAPI:
    """tools: {tool_name: (description, callable(payload_dict) -> dict)}"""
    app = FastAPI(title=f"{server}-mcp")

    @app.get("/health")
    def health():
        return {"status": "ok", "mcp_server": server, "version": "0.2.0-day2"}

    @app.get("/tools")
    def list_tools():
        return {"server": server, "tools": [{"name": name, "description": desc} for name, (desc, _) in tools.items()]}

    @app.post("/tools/call")
    def call(payload: dict, request: Request):
        if not is_authorized(request.headers):
            return JSONResponse(status_code=401, content={"error": "Unauthorized: send Authorization: Bearer <AGENT_API_TOKEN>."})
        name = payload.get("tool") or payload.get("name")
        args = payload.get("args") or payload.get("arguments") or {}
        if name not in tools:
            return JSONResponse(status_code=400, content={"error": f"Unknown tool {name} for {server}", "known_tools": sorted(tools)})
        _, fn = tools[name]
        try:
            result = fn(**args) if isinstance(args, dict) else fn(args)
        except TypeError as e:
            return JSONResponse(status_code=400, content={"error": f"Bad arguments for {name}: {e}", "tool": name})
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": f"Tool {name} failed: {e}", "tool": name})
        return {"server": server, "tool": name, "result": result}
    return app
