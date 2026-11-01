"""MCP Streamable-HTTP client (Day 2b), async-first with a sync wrapper.

Usage (async):
    result = await call_fastmcp("http://filings-mcp:8101", "get_company_facts", {"ticker": "GOOGL"})

Usage (sync, e.g. from a script or a future Scout path):
    result = call_fastmcp_sync("http://filings-mcp:8101", "get_company_facts", {"ticker": "GOOGL"})

The client opens a fresh session per call. That is simple and
correct for a briefing pipeline that makes a handful of calls,
but it is not a pooled connection — a high-throughput caller
would want one session reused across calls instead.

Auth: when AGENT_API_TOKEN is set, it is sent as a Bearer
header via the httpx client, matching the server's /mcp gate
in mesh/mcp_fast.py. (mcp 2.x's streamable_http_client takes
headers only via an httpx AsyncClient, not as a kwarg, and
yields (read, write) — not a session id.)

Transport note: httpx is created with trust_env=False. The
VM's egress proxy breaks httpx URL parsing (the known
"Invalid port: ':1]'" failure); in-stack calls need no proxy,
and Docker service names must not go through one either.
"""
from __future__ import annotations

import asyncio

import httpx

from .auth import auth_headers
from .mcp_fast import parse_tool_result


async def call_fastmcp(base_url: str, tool: str, args: dict | None = None) -> dict:
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with httpx.AsyncClient(headers=auth_headers(), trust_env=False) as http_client:
        async with streamable_http_client(
            f"{base_url.rstrip('/')}/mcp/", http_client=http_client
        ) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool, arguments=args or {})
                return parse_tool_result(result)


async def list_fastmcp_tools_async(base_url: str) -> list[dict]:
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with httpx.AsyncClient(headers=auth_headers(), trust_env=False) as http_client:
        async with streamable_http_client(
            f"{base_url.rstrip('/')}/mcp/", http_client=http_client
        ) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                return [{"name": t.name, "description": t.description} for t in tools.tools]


def list_fastmcp_tools(base_url: str) -> list[dict]:
    """Sync helper: list tools from a /mcp endpoint."""
    return asyncio.run(list_fastmcp_tools_async(base_url))


def call_fastmcp_sync(base_url: str, tool: str, args: dict | None = None) -> dict:
    return asyncio.run(call_fastmcp(base_url, tool, args or {}))
