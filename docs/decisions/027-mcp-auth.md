# ADR 027 — MCP server auth

## Decision

Tej, Nov 4, 2026: ship the MCP server with auth,
not authless. Mechanism: bearer token, enforced in
the Worker itself (not an edge-only rule, so the
protection travels with the code).

## Shape

- `src/index.ts` wraps `createMcpHandler` with a
  gate: `Authorization: Bearer <token>` must match
  the Worker Secret `MCP_AUTH_TOKEN`.
- Constant-time comparison; wrong token and missing
  token both return HTTP 401 + JSON-RPC error
  `-32001` (no oracle for which part failed).
- Fail-closed: no secret configured → refuse
  everything. Local dev uses `.dev.vars`
  (gitignored) with a throwaway test token.
- Worker renamed `remote-mcp-server-authless` →
  `agent-mesh-mcp`; lives in `mcp-server/` in this
  repo so Workers Builds connects to it like the
  search-log Worker (`cd mcp-server && npm ci` /
  `npx wrangler deploy`).

## Verified

Local `wrangler dev`: no header → 401, wrong
token → 401, test token → initialize 200
(`Agent Mesh Earnings` 1.0.0) + tools/list.
(Tools/call against live EDGAR still cannot be
proven inside the sandbox — workerd TLS limit,
known since Nov 2 — so full proof happens on the
deployed Worker.)

## Still to do at deploy time

1. Workers Builds project `agent-mesh-mcp` +
   deploy.
2. Tej sets the `MCP_AUTH_TOKEN` secret in the
   dashboard (value never in chat or the repo).
3. Live gate check: unauthenticated request → 401.
4. Tej's authenticated check in MCP Inspector
   (only he holds the token) — the one step that
   cannot be verified without it.
