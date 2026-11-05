/**
 * Transcript archive log for the Agent Mesh Earnings site (Batch 27,
 * Phase 1).
 *
 * POST /log {ticker, quarter_label, quarter_end, source_url, excerpt,
 * source_type?} saves one archived transcript excerpt: what Scout
 * already fetched for a briefing. GET /transcript?ticker=X&
 * quarter_end=YYYY-MM-DD returns the archived row. GET /recent
 * lists archived rows (metadata only — excerpts stay behind
 * /transcript). GET /stats counts rows by source type.
 *
 * The archive is for agent analysis; the UI shows excerpts and
 * derived analysis, never a republished full third-party
 * transcript. Rows dedupe on (ticker, quarter_end, source_url),
 * so a briefing Refresh re-logs nothing. source_type is "text"
 * for fetched transcripts and "asr" for Whisper transcriptions
 * (Phase 2b) — ASR text is never a story source and no number
 * from it may enter a briefing.
 *
 * Privacy, deliberate: rows store ONLY the briefing's own
 * transcript data (ticker, quarter, source URL, excerpt text).
 * No IP, no user agent, no fingerprint. The log endpoint is
 * public by design (the Orchestrator Worker calls it
 * server-side), so validation caps shape, not intent.
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

const MAX_TICKER = 12;
const MAX_LABEL = 80;
const MAX_URL = 2000;
const MAX_EXCERPT = 100000;
const MAX_SOURCE_TYPE = 16;

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
		`CREATE TABLE IF NOT EXISTS transcripts (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			ticker TEXT NOT NULL,
			quarter_label TEXT,
			quarter_end TEXT,
			source_url TEXT NOT NULL,
			excerpt TEXT NOT NULL,
			source_type TEXT NOT NULL DEFAULT 'text',
			fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
			UNIQUE(ticker, quarter_end, source_url)
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
			const ticker =
				typeof body.ticker === "string"
					? body.ticker.trim().toUpperCase().slice(0, MAX_TICKER)
					: "";
			const quarterLabel =
				typeof body.quarter_label === "string"
					? body.quarter_label.trim().slice(0, MAX_LABEL)
					: "";
			const quarterEnd =
				typeof body.quarter_end === "string"
					? body.quarter_end.trim().slice(0, 10)
					: "";
			const sourceUrl =
				typeof body.source_url === "string"
					? body.source_url.trim().slice(0, MAX_URL)
					: "";
			const excerpt =
				typeof body.excerpt === "string"
					? body.excerpt.slice(0, MAX_EXCERPT)
					: "";
			const sourceType =
				typeof body.source_type === "string" && body.source_type.trim()
					? body.source_type.trim().toLowerCase().slice(0, MAX_SOURCE_TYPE)
					: "text";
			if (!ticker || !sourceUrl || !excerpt) {
				return json({ error: "ticker, source_url and excerpt are required" }, 400);
			}
			if (sourceType !== "text" && sourceType !== "asr") {
				return json({ error: "source_type must be text or asr" }, 400);
			}
			await ensureTable(env);
			await env.DB.prepare(
				"INSERT OR IGNORE INTO transcripts (ticker, quarter_label, quarter_end, source_url, excerpt, source_type) VALUES (?, ?, ?, ?, ?, ?)",
			).bind(ticker, quarterLabel || null, quarterEnd || null, sourceUrl, excerpt, sourceType).run();
			return json({ ok: true });
		}

		if (url.pathname === "/transcript" && request.method === "GET") {
			const ticker = (url.searchParams.get("ticker") ?? "").trim().toUpperCase();
			const quarterEnd = (url.searchParams.get("quarter_end") ?? "").trim();
			if (!ticker || !quarterEnd) {
				return json({ error: "ticker and quarter_end are required" }, 400);
			}
			await ensureTable(env);
			const { results } = await env.DB.prepare(
				"SELECT id, ticker, quarter_label, quarter_end, source_url, excerpt, source_type, fetched_at FROM transcripts WHERE ticker = ? AND quarter_end = ? LIMIT 1",
			).bind(ticker, quarterEnd).all();
			if (!results.length) return json({ error: "not found" }, 404);
			return json({ transcript: results[0] });
		}

		if (url.pathname === "/recent" && request.method === "GET") {
			const parsed = parseInt(url.searchParams.get("limit") ?? "50", 10);
			const limit = Math.min(100, Math.max(1, Number.isNaN(parsed) ? 50 : parsed));
			await ensureTable(env);
			const { results } = await env.DB.prepare(
				"SELECT id, ticker, quarter_label, quarter_end, source_url, source_type, fetched_at, LENGTH(excerpt) AS excerpt_chars FROM transcripts ORDER BY id DESC LIMIT ?",
			).bind(limit).all();
			return json({ transcripts: results });
		}

		if (url.pathname === "/stats" && request.method === "GET") {
			await ensureTable(env);
			const { results: byType } = await env.DB.prepare(
				"SELECT source_type, COUNT(*) AS count FROM transcripts GROUP BY source_type",
			).all();
			const { results: totalRows } = await env.DB.prepare(
				"SELECT COUNT(*) AS n, COUNT(DISTINCT ticker) AS tickers FROM transcripts",
			).all();
			const total = (totalRows[0] as { n?: number; tickers?: number } | undefined) ?? {};
			return json({ total: total.n ?? 0, tickers: total.tickers ?? 0, by_source_type: byType });
		}

		return json({ error: "not found" }, 404);
	},
};
