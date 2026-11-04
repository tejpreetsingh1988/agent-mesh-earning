# Agent Mesh MCP server

Remote MCP server exposing the Scout's EDGAR tools over
Streamable HTTP, built with the Cloudflare Agents SDK
(`McpServer` + `createMcpHandler`, TypeScript, no
Durable Objects binding — stateless).

## Tools

- `get_company_facts` — quarterly facts by metric
  (10-Q rows, 60–100 day duration, derived Q4)
- `list_recent_filings` — recent filings for a ticker
- `get_latest_earnings_filing` — latest earnings 8-K
- `get_filing_facts` — filing facts, optional
  `report_date` (companyfacts fallback included)

Implementation is a faithful TypeScript port of the
Python `mesh/edgar.py` + `mesh/edgar_facts.py`
(recency pick with priority tie-break, companyfacts
fallback with the 400-day stale guard, empty-units
guard — the Visa failure mode).

## Auth — required, fail-closed

Every request must carry
`Authorization: Bearer <token>` matching the Worker
Secret **`MCP_AUTH_TOKEN`**. The gate runs before
any tool code, compares in constant time, and
refuses with HTTP 401 + JSON-RPC error otherwise.
With no secret configured, the server refuses
everything — an unconfigured server must not
silently become public.

The token value is never committed, never logged,
and never appears in this repo. To set it: the
Worker's dashboard → Settings → Variables → add a
Secret named `MCP_AUTH_TOKEN` with a value you
generate. To use it in MCP Inspector: connect to
`https://agent-mesh-mcp.tejpreetsingh1988.workers.dev/mcp`
and add the request header
`Authorization: Bearer <your token>`.

Local dev uses `.dev.vars` (gitignored) with a
throwaway test token — never the real secret.

## Deploy

Workers Builds project `agent-mesh-mcp`, connected
to this repo, branch main:

- Build command: `cd mcp-server && npm ci`
- Deploy command: `cd mcp-server && npx wrangler deploy`
- Protect with Cloudflare Access: OFF (the bearer
  gate is the auth; Access would double-gate
  non-browser MCP clients)

URL: `https://agent-mesh-mcp.tejpreetsingh1988.workers.dev/mcp`
