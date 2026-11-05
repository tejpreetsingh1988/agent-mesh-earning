/**
 * Stream resume log for the Agent Mesh Earnings site (Batch 31).
 *
 * The Orchestrator Worker's SSE stream is not resumable by itself:
 * when the browser's connection breaks, the pipeline task is
 * cancelled and the run dies. So the Orchestrator stores, per
 * run_id, (a) a stage checkpoint — the Scout pack, Analyst
 * analysis, Critic PASS critique, or final briefing, whichever
 * stage finished last — and (b) every stream event in order.
 * A later ?resume_run_id= request replays the stored events,
 * then runs only the unfinished stages under the same run_id.
 *
 * POST /checkpoint {run_id, ticker, quarter, stage, pack?,
 *   analysis?, critique?, briefing?} upserts the run row; only
 *   the fields present in the body overwrite stored ones, so a
 *   later stage never wipes an earlier stage's output. stage is
 *   one of started/scout/analyst/critic/done.
 * POST /event {run_id, seq, event} appends one event; (run_id,
 *   seq) is the primary key, so a replayed or retried POST is a
 *   no-op instead of a duplicate.
 * GET /resume?run_id=X returns {run, events} or 404 when the
 *   run never started (no checkpoint row). run carries the
 *   stored stage outputs parsed back to JSON.
 * GET /stats counts runs and events.
 *
 * Retention: every checkpoint POST also deletes runs (and
 * their events) not updated in 7 days. A resume happens minutes
 * after a break; a week of history is generous, and the tables
 * must not grow unbounded on the free D1 tier.
 *
 * Privacy, deliberate: rows store ONLY the briefing pipeline's
 * own outputs (packs, analyses, critiques, briefings, events).
 * No IP, no user agent, no fingerprint. The endpoints are
 * public by design (the Orchestrator Worker calls them
 * server-side), so validation caps shape, not intent: run_id
 * is a random uuid, unguessable, and the data is public
 * briefing data anyway.
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

const MAX_RUN_ID = 64;
const MAX_TICKER = 12;
const MAX_QUARTER = 40;
const STAGES = ["started", "scout", "analyst", "critic", "done"];
const MAX_EVENT_CHARS = 500000;
const MAX_FIELD_CHARS = 2000000;

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

async function ensureTables(env: Env): Promise<void> {
	await env.DB.prepare(
		`CREATE TABLE IF NOT EXISTS stream_runs (
			run_id TEXT PRIMARY KEY, ticker TEXT, quarter TEXT,
			stage TEXT, pack TEXT, analysis TEXT, critique TEXT,
			briefing TEXT, updated_at TEXT DEFAULT (datetime('now')))`
	).run();
	await env.DB.prepare(
		`CREATE TABLE IF NOT EXISTS stream_events (
			run_id TEXT, seq INTEGER, event TEXT,
			PRIMARY KEY (run_id, seq))`
	).run();
}

async function pruneOld(env: Env): Promise<void> {
	await env.DB.prepare(
		`DELETE FROM stream_events WHERE run_id IN (
			SELECT run_id FROM stream_runs
			WHERE updated_at < datetime('now', '-7 days'))`
	).run();
	await env.DB.prepare(
		`DELETE FROM stream_runs
			WHERE updated_at < datetime('now', '-7 days')`
	).run();
}

function asText(value: unknown, max: number): string | null {
	if (typeof value !== "string" || value.length === 0 || value.length > max) return null;
	return value;
}

function asJsonText(value: unknown, max: number): string | null {
	// Checkpoint fields arrive as objects; store them stringified.
	// A string is accepted as-is (the Orchestrator sends objects).
	if (value === undefined || value === null) return null;
	const text = typeof value === "string" ? value : JSON.stringify(value);
	if (text.length > max) return null;
	return text;
}

function parseJson(text: unknown): unknown {
	if (typeof text !== "string") return null;
	try {
		return JSON.parse(text);
	} catch {
		return null;
	}
}

export default {
	async fetch(request: Request, env: Env): Promise<Response> {
		const url = new URL(request.url);
		if (request.method === "OPTIONS") {
			return new Response(null, { headers: CORS });
		}
		try {
			if (request.method === "POST" && url.pathname === "/checkpoint") {
				const body = (await request.json()) as Record<string, unknown>;
				const runId = asText(body.run_id, MAX_RUN_ID);
				const ticker = asText(body.ticker, MAX_TICKER);
				const quarter = body.quarter === "" ? "" : asText(body.quarter, MAX_QUARTER);
				const stage = typeof body.stage === "string" && STAGES.includes(body.stage)
					? body.stage : null;
				if (!runId || !ticker || quarter === null || !stage) {
					return json({ error: "run_id, ticker, quarter, and a valid stage are required" }, 400);
				}
				const pack = asJsonText(body.pack, MAX_FIELD_CHARS);
				const analysis = asJsonText(body.analysis, MAX_FIELD_CHARS);
				const critique = asJsonText(body.critique, MAX_FIELD_CHARS);
				const briefing = asJsonText(body.briefing, MAX_FIELD_CHARS);
				if ((body.pack !== undefined && pack === null)
					|| (body.analysis !== undefined && analysis === null)
					|| (body.critique !== undefined && critique === null)
					|| (body.briefing !== undefined && briefing === null)) {
					return json({ error: "a checkpoint field exceeds the size cap" }, 400);
				}
				await ensureTables(env);
				// COALESCE keeps the stored value when the body
				// omits that field, so stages accumulate.
				await env.DB.prepare(
					`INSERT INTO stream_runs
						(run_id, ticker, quarter, stage, pack, analysis, critique, briefing)
						VALUES (?, ?, ?, ?, ?, ?, ?, ?)
						ON CONFLICT(run_id) DO UPDATE SET
						ticker = excluded.ticker, quarter = excluded.quarter,
						stage = excluded.stage,
						pack = COALESCE(excluded.pack, stream_runs.pack),
						analysis = COALESCE(excluded.analysis, stream_runs.analysis),
						critique = COALESCE(excluded.critique, stream_runs.critique),
						briefing = COALESCE(excluded.briefing, stream_runs.briefing),
						updated_at = datetime('now')`
				).bind(runId, ticker, quarter, stage, pack, analysis, critique, briefing).run();
				await pruneOld(env);
				return json({ ok: true });
			}
			if (request.method === "POST" && url.pathname === "/event") {
				const body = (await request.json()) as Record<string, unknown>;
				const runId = asText(body.run_id, MAX_RUN_ID);
				const seq = typeof body.seq === "number" && Number.isInteger(body.seq) && body.seq >= 0
					? body.seq : null;
				const event = asJsonText(body.event, MAX_EVENT_CHARS);
				if (!runId || seq === null || event === null) {
					return json({ error: "run_id, integer seq, and event are required" }, 400);
				}
				await ensureTables(env);
				await env.DB.prepare(
					`INSERT OR IGNORE INTO stream_events (run_id, seq, event)
						VALUES (?, ?, ?)`
				).bind(runId, seq, event).run();
				return json({ ok: true });
			}
			if (request.method === "GET" && url.pathname === "/resume") {
				const runId = url.searchParams.get("run_id") || "";
				if (!runId || runId.length > MAX_RUN_ID) {
					return json({ error: "run_id is required" }, 400);
				}
				await ensureTables(env);
				const runs = await env.DB.prepare(
					`SELECT run_id, ticker, quarter, stage, pack, analysis,
						critique, briefing, updated_at FROM stream_runs
						WHERE run_id = ? LIMIT 1`
				).bind(runId).all();
				const row = runs.results[0];
				if (!row) return json({ error: "unknown run_id" }, 404);
				const events = await env.DB.prepare(
					`SELECT seq, event FROM stream_events
						WHERE run_id = ? ORDER BY seq ASC`
				).bind(runId).all();
				return json({
					run: {
						run_id: row.run_id, ticker: row.ticker,
						quarter: row.quarter, stage: row.stage,
						pack: parseJson(row.pack),
						analysis: parseJson(row.analysis),
						critique: parseJson(row.critique),
						briefing: parseJson(row.briefing),
						updated_at: row.updated_at,
					},
					events: events.results.map((r) => ({
						seq: r.seq, event: parseJson(r.event),
					})),
				});
			}
			if (request.method === "GET" && url.pathname === "/stats") {
				await ensureTables(env);
				const runs = await env.DB.prepare(
					`SELECT COUNT(*) AS n FROM stream_runs`
				).all();
				const events = await env.DB.prepare(
					`SELECT COUNT(*) AS n FROM stream_events`
				).all();
				return json({
					runs: runs.results[0]?.n ?? 0,
					events: events.results[0]?.n ?? 0,
				});
			}
			return json({ error: "not found" }, 404);
		} catch (e) {
			return json({ error: e instanceof Error ? e.message : "failed" }, 500);
		}
	},
};
