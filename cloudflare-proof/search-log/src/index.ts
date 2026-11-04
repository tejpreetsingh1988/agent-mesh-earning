/**
 * Search logging for the Agent Mesh Earnings site.
 *
 * POST /log {query, ticker?} saves one row: what a visitor
 * searched for, and which company they picked. GET /recent
 * returns the latest rows so the site owner can see what
 * users are searching for.
 *
 * Privacy, deliberate: rows store ONLY query text, ticker,
 * and timestamp. No IP, no user agent, no fingerprint.
 * The log endpoint is public by design (the static site
 * calls it), so validation caps shape, not intent — abuse
 * protection is out of v1 scope.
 */

interface D1Statement {
	bind(...args: unknown[]): D1Statement;
	run(): Promise<unknown>;
	all(): Promise<{ results: Record<string, unknown>[] }>;
}

interface D1Database {
	prepare(sql: string): D1Statement;
}

interface Env {
	DB: D1Database;
}

const MAX_QUERY = 100;
const MAX_TICKER = 12;

const CORS = {
	"Access-Control-Allow-Origin": "*",
	"Access-Control-Allow-Methods": "POST, GET, OPTIONS",
	"Access-Control-Allow-Headers": "Content-Type",
};

function json(data: unknown, status = 200): Response {
	return new Response(JSON.stringify(data), {
		status,
		headers: { "Content-Type": "application/json", ...CORS },
	});
}

async function ensureTable(env: Env): Promise<void> {
	await env.DB.prepare(
		`CREATE TABLE IF NOT EXISTS searches (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			query TEXT NOT NULL,
			ticker TEXT,
			created_at TEXT NOT NULL DEFAULT (datetime('now'))
		)`,
	).run();
}

export default {
	async fetch(request: Request, env: Env): Promise<Response> {
		const url = new URL(request.url);

		if (request.method === "OPTIONS") {
			return new Response(null, { headers: CORS });
		}

		if (url.pathname === "/log" && request.method === "POST") {
			let body: Record<string, unknown>;
			try {
				body = (await request.json()) as Record<string, unknown>;
			} catch {
				return json({ error: "invalid JSON" }, 400);
			}
			const query =
				typeof body.query === "string" ? body.query.trim().slice(0, MAX_QUERY) : "";
			const ticker =
				typeof body.ticker === "string"
					? body.ticker.trim().toUpperCase().slice(0, MAX_TICKER) || null
					: null;
			if (!query) return json({ error: "query required" }, 400);
			await ensureTable(env);
			await env.DB.prepare("INSERT INTO searches (query, ticker) VALUES (?, ?)").bind(
				query,
				ticker,
			).run();
			return json({ ok: true });
		}

		if (url.pathname === "/stats" && request.method === "GET") {
			await ensureTable(env);
			const { results: top } = await env.DB.prepare(
				"SELECT query, COUNT(*) AS count, MAX(created_at) AS last FROM searches GROUP BY LOWER(query) ORDER BY count DESC, last DESC LIMIT 10",
			).all();
			const { results: totalRows } = await env.DB.prepare(
				"SELECT COUNT(*) AS n FROM searches",
			).all();
			const total = (totalRows[0] as { n?: number } | undefined)?.n ?? 0;
			return json({ total, top });
		}

		if (url.pathname === "/recent" && request.method === "GET") {
			const parsed = parseInt(url.searchParams.get("limit") ?? "50", 10);
			const limit = Math.min(100, Math.max(1, Number.isNaN(parsed) ? 50 : parsed));
			await ensureTable(env);
			const { results } = await env.DB.prepare(
				"SELECT id, query, ticker, created_at FROM searches ORDER BY id DESC LIMIT ?",
			).bind(limit).all();
			return json({ searches: results });
		}

		return json({ error: "not found" }, 404);
	},
};
