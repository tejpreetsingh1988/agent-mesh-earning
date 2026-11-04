import { McpServer } from "@modelcontextprotocol/server";
import { createMcpHandler } from "agents/mcp/server";
import { z } from "zod";
import {
	getCompanyFacts,
	getFilingFacts,
	getLatestEarningsFiling,
	listRecentFilings,
} from "./edgar";

function textResult(value: unknown) {
	return { content: [{ type: "text" as const, text: JSON.stringify(value, null, 2) }] };
}

function createServer() {
	const server = new McpServer({
		name: "Agent Mesh Earnings",
		version: "1.0.0",
	});

	server.registerTool(
		"get_company_facts",
		{ inputSchema: z.object({ ticker: z.string().min(1).max(10) }) },
		async ({ ticker }) => textResult(await getCompanyFacts(ticker)),
	);

	server.registerTool(
		"list_recent_filings",
		{
			inputSchema: z.object({
				ticker: z.string().min(1).max(10),
				limit: z.number().int().min(1).max(50).optional(),
			}),
		},
		async ({ ticker, limit }) => textResult(await listRecentFilings(ticker, limit ?? 10)),
	);

	server.registerTool(
		"get_latest_earnings_filing",
		{ inputSchema: z.object({ ticker: z.string().min(1).max(10) }) },
		async ({ ticker }) => textResult(await getLatestEarningsFiling(ticker)),
	);

	server.registerTool(
		"get_filing_facts",
		{
			inputSchema: z.object({
				ticker: z.string().min(1).max(10),
				report_date: z.string().optional(),
			}),
		},
		async ({ ticker, report_date }) => textResult(await getFilingFacts(ticker, report_date ?? "")),
	);

	return server;
}

const handler = createMcpHandler(createServer);

// Bearer-token gate (added Nov 4, 2026 — Tej chose auth
// over shipping authless). The token lives ONLY as a
// Worker Secret named MCP_AUTH_TOKEN, set in the
// dashboard; it is never committed, never logged, and
// never appears in this repo. Comparison is
// constant-time so a wrong token leaks nothing about
// the right one. Fail-closed: with no secret
// configured, every request is refused — an
// unconfigured server must not silently become
// public. Local dev uses .dev.vars (gitignored) with
// a throwaway test token, never the real secret.
function timingSafeEqual(a: string, b: string): boolean {
	if (a.length !== b.length) return false;
	let diff = 0;
	for (let i = 0; i < a.length; i++) {
		diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
	}
	return diff === 0;
}

function isAuthorized(request: Request, env: Env): boolean {
	const expected = (env as { MCP_AUTH_TOKEN?: string }).MCP_AUTH_TOKEN;
	if (!expected) return false;
	const header = request.headers.get("Authorization") ?? "";
	if (!header.startsWith("Bearer ")) return false;
	return timingSafeEqual(header.slice("Bearer ".length), expected);
}

export default {
	fetch(request: Request, env: Env, ctx: ExecutionContext) {
		if (!isAuthorized(request, env)) {
			return new Response(
				JSON.stringify({
					jsonrpc: "2.0",
					error: {
						code: -32001,
						message:
							"Unauthorized: send Authorization: Bearer <token> matching the MCP_AUTH_TOKEN secret on this Worker.",
					},
					id: null,
				}),
				{
					status: 401,
					headers: { "Content-Type": "application/json" },
				},
			);
		}
		return handler(request, env, ctx);
	},
} satisfies ExportedHandler<Env>;
