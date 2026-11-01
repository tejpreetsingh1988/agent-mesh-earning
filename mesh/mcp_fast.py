"""Day 2b — real MCP transport (Streamable HTTP) alongside the legacy
HTTP JSON transport, not instead of it yet.

Why alongside: the legacy `/tools` + `/tools/call` endpoints are
what Scout, Critic, and the Windows Docker proof use today, and
they work. The MCPServer app below mounts the *same* tool
functions at `/mcp` under the real MCP protocol (JSON-RPC over
Streamable HTTP, via the `mcp` package, v2 `MCPServer`). Nothing
is re-implemented: the tool dict is shared, so a tool cannot
drift between transports.

Migration status, stated plainly:
- Server: live at `/mcp` on every MCP server (see each
  `mcp_servers/*/main.py`, `fast_app`), with the same Bearer
  token gate as `/tools/call` when AGENT_API_TOKEN is set.
- Client: `mesh/mcp_fast_client.py` provides an async MCP
  client and a sync wrapper. Scout/Critic still use the legacy
  client by default — switching them is a separate, tested
  step, not a silent flag flip, because the MCP client is
  async and session-based while Scout is sync.
- If `mcp` is not installed, `create_fastmcp_app` raises
  ImportError and the server modules fall back to the legacy
  app only (fast_app = None). Legacy behaviour never breaks
  because the new transport is unavailable.
"""
from __future__ import annotations

import json

from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Mount

from .auth import is_authorized


class _McpAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path.startswith("/mcp"):
            if not is_authorized(request.headers):
                return JSONResponse(
                    status_code=401,
                    content={"error": "Unauthorized: send Authorization: Bearer <AGENT_API_TOKEN>."},
                )
        return await call_next(request)


def create_mcp_server(server_name: str, tools: dict):
    """Register the shared tool dict on a real MCPServer.

    tools: {name: (description, callable)} — the same dict the
    legacy app uses. Tool functions must have annotated
    parameters (all of this project's do); unannotated or
    **kwargs functions cannot be registered and will raise,
    which is the point — the protocol needs a schema.
    """
    from mcp.server.mcpserver import MCPServer

    server = MCPServer(server_name)
    for name, (description, fn) in tools.items():
        server.tool(name=name, description=description)(fn)
    return server


def create_fastmcp_app(server_name: str, tools: dict, legacy_app=None):
    """Starlette app: legacy FastAPI app at `/`, MCP at `/mcp`.

    Pass the legacy app (from mesh.mcp_real.create_mcp_app) so
    /health, /tools, and /tools/call keep working unchanged.
    """
    mcp_server = create_mcp_server(server_name, tools)
    # Mount strips the /mcp prefix before the inner app sees the
    # request, so the inner app must serve at "/" — not its
    # default "/mcp", which would 404 under the mount.
    mcp_app = mcp_server.streamable_http_app(streamable_http_path="/")
    routes = [Mount("/mcp", app=mcp_app)]
    if legacy_app is not None:
        routes.append(Mount("/", app=legacy_app))

    # Lifespan forwarding: uvicorn only runs the *root* app's
    # lifespan, and the MCP session manager needs its lifespan
    # started ("Task group is not initialized" otherwise).
    # Entering the mounted app's lifespan context here starts it.
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(_app):
        async with mcp_app.router.lifespan_context(mcp_app):
            yield

    app = Starlette(routes=routes, lifespan=lifespan)
    app.add_middleware(_McpAuthMiddleware)
    return app


def parse_tool_result(result) -> dict:
    """Extract the dict a tool returned, from an MCP CallToolResult.

    MCP tools return content blocks; a dict return value arrives
    as a JSON text block, or as structuredContent when the
    server provides it. Anything else is wrapped, never dropped
    silently, so a caller can see what actually came back.
    """
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            try:
                parsed = json.loads(text)
            except Exception:
                return {"text": text}
            if isinstance(parsed, dict):
                return parsed
            return {"value": parsed}
    return {"error": "MCP tool returned no parseable content", "result": str(result)}
