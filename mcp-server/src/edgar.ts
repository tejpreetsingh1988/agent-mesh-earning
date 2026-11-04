/**
 * Filing-verified facts from SEC EDGAR XBRL — TypeScript port of
 * the Python mesh/edgar.py + mesh/edgar_facts.py logic, including
 * the MSFT recency-aware tag pick (ADR: pick_latest_tag) and the
 * Visa companyfacts fallback (ADR 021).
 *
 * Rules, mirrored exactly from the Python originals:
 * - A quarterly fact comes only from a 10-Q row whose
 *   start-to-end duration is 60-100 days. YTD rows, 10-K FY
 *   rows, and instant rows (no start) are excluded.
 * - Q4 is derived as FY minus 9-month YTD, labelled derived.
 * - The tag whose rows reach the most recent quarter wins;
 *   on a tie the earlier-priority tag stands.
 * - When a metric's companyconcept pick is empty or more than
 *   400 days stale versus the report date, the same tags are
 *   re-read from the one companyfacts payload (fetched at most
 *   once per call) and the pick is redone.
 * - Nothing here invents a figure: a metric with no quarterly
 *   row is reported in `missing`, never fabricated.
 */

const UA = "Agent Mesh Research Lab research@example.com";

const ALTERNATE_TAGS: Record<string, string[]> = {
	total_revenue: [
		"Revenues",
		"RevenueFromContractWithCustomerExcludingAssessedTax",
		"SalesRevenueNet",
		"SalesRevenueGoodsNet",
		"TotalRevenues",
		"RevenuesNetOfInterestExpense",
	],
	operating_income: [
		"OperatingIncomeLoss",
		"OperatingIncomeLossBeforeMinorityInterest",
	],
	gaap_eps: ["EarningsPerShareDiluted", "EarningsPerShareBasic"],
};

const STALE_PICK_DAYS = 400;

export interface RawRow {
	form?: string;
	start?: string;
	end?: string;
	val?: number;
	filed?: string;
	accn?: string;
}

export interface Row {
	metric: string;
	value: number | undefined;
	unit: string;
	period_end: string | undefined;
	period_start: string | undefined;
	duration_days: number | null;
	form: string | undefined;
	filed: string | undefined;
	accession: string | undefined;
	derived?: boolean;
	derivation?: string;
}

type Concept = { units?: Record<string, RawRow[] | Record<string, never>> };

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function getJson(url: string): Promise<any> {
	const res = await fetch(url, { headers: { "User-Agent": UA } });
	if (!res.ok) throw new Error(`EDGAR HTTP ${res.status} for ${url}`);
	return res.json();
}

function padCik(cik: number): string {
	return String(cik).padStart(10, "0");
}

export async function getCompanyFacts(ticker: string) {
	const t = ticker.trim().toUpperCase();
	const tickers = await getJson("https://www.sec.gov/files/company_tickers.json");
	for (const v of Object.values(tickers) as any[]) {
		if (v.ticker === t) {
			const cik = Number(v.cik_str);
			return {
				ticker: t,
				company_name: v.title,
				cik,
				cik_padded: padCik(cik),
				source: "SEC EDGAR company_tickers.json",
			};
		}
	}
	return { error: `Ticker ${t} not found in SEC EDGAR tickers`, ticker: t };
}

async function getSubmissions(cikPadded: string): Promise<any> {
	return getJson(`https://data.sec.gov/submissions/CIK${cikPadded}.json`);
}

export async function listRecentFilings(ticker: string, limit = 10) {
	const facts: any = await getCompanyFacts(ticker);
	if (facts.error) return facts;
	const sub = await getSubmissions(facts.cik_padded);
	const recent = sub.filings.recent;
	const out = [];
	const n = Math.min(limit, recent.form.length);
	for (let i = 0; i < n; i++) {
		const acc = recent.accessionNumber[i];
		out.push({
			form: recent.form[i],
			filingDate: recent.filingDate[i],
			accessionNumber: acc,
			primaryDocument: recent.primaryDocument[i],
			reportDate: recent.reportDate ? recent.reportDate[i] : "",
			url: `https://www.sec.gov/Archives/edgar/data/${facts.cik}/${acc.replace(/-/g, "")}/${recent.primaryDocument[i]}`,
		});
	}
	return { ticker: facts.ticker, company_name: facts.company_name, cik: facts.cik, filings: out };
}

export async function getLatestEarningsFiling(ticker: string) {
	const facts: any = await getCompanyFacts(ticker);
	if (facts.error) return facts;
	const sub = await getSubmissions(facts.cik_padded);
	const recent = sub.filings.recent;
	let idx = recent.form.indexOf("8-K");
	if (idx === -1) idx = 0;
	const acc = recent.accessionNumber[idx];
	const doc = recent.primaryDocument[idx];
	return {
		ticker: facts.ticker,
		company_name: facts.company_name,
		cik: facts.cik,
		form: recent.form[idx],
		filingDate: recent.filingDate[idx],
		accessionNumber: acc,
		primaryDocument: doc,
		url: `https://www.sec.gov/Archives/edgar/data/${facts.cik}/${acc.replace(/-/g, "")}/${doc}`,
		note: "8-K is the usual earnings-release filing. Verify the quarter in the document text — do not assume it from the filing date alone.",
	};
}

function durationDays(row: RawRow): number | null {
	if (!row.start || !row.end) return null;
	const ms = Date.parse(row.end) - Date.parse(row.start);
	if (Number.isNaN(ms)) return null;
	return Math.round(ms / 86400000);
}

function parseConceptRows(concept: Concept, metric: string): Row[] {
	const out: Row[] = [];
	const units = concept.units ?? {};
	for (const [unit, rows] of Object.entries(units)) {
		// Visa's failure mode: units.USD is {} (not a list) — skip it.
		if (!Array.isArray(rows)) continue;
		for (const row of rows) {
			if (row.form !== "10-Q") continue;
			const duration = durationDays(row);
			if (duration === null || duration < 60 || duration > 100) continue;
			out.push({
				metric,
				value: row.val,
				unit,
				period_end: row.end,
				period_start: row.start,
				duration_days: duration,
				form: row.form,
				filed: row.filed,
				accession: row.accn,
			});
		}
	}
	// Dedupe: same quarter re-filed as a comparative figure —
	// keep the latest-filed version of each (start, end) pair.
	out.sort((a, b) => (b.filed ?? "").localeCompare(a.filed ?? ""));
	const seen = new Set<string>();
	const deduped: Row[] = [];
	for (const row of out) {
		const key = `${row.period_start}|${row.period_end}`;
		if (seen.has(key)) continue;
		seen.add(key);
		deduped.push(row);
	}
	deduped.sort((a, b) => (b.period_end ?? "").localeCompare(a.period_end ?? ""));
	return deduped;
}

function deriveQ4Rows(concept: Concept, metric: string): Row[] {
	const ytd = new Map<number, RawRow>();
	const fy = new Map<number, RawRow>();
	const units = concept.units ?? {};
	for (const rows of Object.values(units)) {
		if (!Array.isArray(rows)) continue;
		for (const row of rows) {
			const duration = durationDays(row);
			if (duration === null || !row.end || !/^\d{4}-/.test(row.end)) continue;
			const year = Number(row.end.slice(0, 4));
			if (row.form === "10-Q" && duration >= 240 && duration <= 290) ytd.set(year, row);
			else if (row.form === "10-K" && duration >= 330 && duration <= 370) fy.set(year, row);
		}
	}
	const out: Row[] = [];
	for (const year of [...ytd.keys()].filter((y) => fy.has(y)).sort()) {
		const y = ytd.get(year)!;
		const f = fy.get(year)!;
		if (y.val === undefined || f.val === undefined || !f.end || !y.end) continue;
		out.push({
			metric,
			value: f.val - y.val,
			unit: "USD",
			period_end: f.end,
			period_start: y.end,
			duration_days: durationDays({ start: y.end, end: f.end }),
			form: "10-K (derived Q4)",
			filed: f.filed,
			accession: f.accn,
			derived: true,
			derivation: `FY ${f.val} minus 9-month YTD ${y.val}`,
		});
	}
	out.sort((a, b) => (b.period_end ?? "").localeCompare(a.period_end ?? ""));
	return out;
}

function rowsFromPayload(payload: Concept, metric: string): Row[] {
	const rows = parseConceptRows(payload, metric);
	if (!rows.length) return [];
	const seen = new Set(rows.map((r) => r.period_end));
	const out = [...rows];
	for (const derived of deriveQ4Rows(payload, metric)) {
		if (!seen.has(derived.period_end)) out.push(derived);
	}
	out.sort((a, b) => (b.period_end ?? "").localeCompare(a.period_end ?? ""));
	return out;
}

function pickLatestTag(candidates: [string, Row[]][]): [string, Row[]] | null {
	let best: [string, string, Row[]] | null = null;
	for (const [tag, rows] of candidates) {
		if (!rows.length) continue;
		const latest = rows[0].period_end ?? "";
		if (best === null || latest > best[1]) best = [tag, latest, rows];
	}
	return best ? [best[0], best[2]] : null;
}

function needsCompanyfactsFallback(
	picked: [string, Row[]] | null,
	reportDate: string | null,
): boolean {
	if (picked === null) return true;
	if (!reportDate) return false;
	const ref = Date.parse(reportDate.slice(0, 10));
	const latest = Date.parse(picked[1][0].period_end ?? "");
	if (Number.isNaN(ref) || Number.isNaN(latest)) return false;
	return (ref - latest) / 86400000 > STALE_PICK_DAYS;
}

function companyfactsTagUnits(cf: any, tag: string): Record<string, RawRow[]> {
	try {
		return cf.facts["us-gaap"][tag].units ?? {};
	} catch {
		return {};
	}
}

export interface QuarterlyFacts {
	metrics: Record<string, { tag: string; rows: Row[] }>;
	missing: string[];
}

export async function getQuarterlyFacts(
	cik: number,
	reportDate: string | null = null,
	limit = 8,
): Promise<QuarterlyFacts> {
	const result: Record<string, { tag: string; rows: Row[] }> = {};
	const missing: string[] = [];
	let cf: any = null;
	let cfFetched = false;
	const fetchCompanyfacts = async () => {
		if (!cfFetched) {
			cfFetched = true;
			try {
				cf = await getJson(`https://data.sec.gov/api/xbrl/companyfacts/CIK${padCik(cik)}.json`);
			} catch {
				cf = null;
			}
		}
		return cf;
	};

	for (const [metric, tags] of Object.entries(ALTERNATE_TAGS)) {
		const candidates: [string, Row[]][] = [];
		for (const tag of tags) {
			// SEC fair access: ~10 requests/second — pause between fetches.
			await sleep(100);
			try {
				const payload = await getJson(
					`https://data.sec.gov/api/xbrl/companyconcept/CIK${padCik(cik)}/us-gaap/${tag}.json`,
				);
				const rows = rowsFromPayload(payload, metric);
				if (rows.length) candidates.push([tag, rows]);
			} catch {
				continue;
			}
		}
		let picked = pickLatestTag(candidates);
		let fallbackTried = false;
		if (needsCompanyfactsFallback(picked, reportDate)) {
			const payload = await fetchCompanyfacts();
			fallbackTried = payload !== null;
			if (payload) {
				for (const tag of tags) {
					const rows = rowsFromPayload({ units: companyfactsTagUnits(payload, tag) }, metric);
					if (rows.length) candidates.push([tag, rows]);
				}
				picked = pickLatestTag(candidates);
			}
		}
		if (picked) {
			result[metric] = { tag: picked[0], rows: picked[1].slice(0, limit) };
		} else {
			let note = `No quarterly-duration 10-Q row for ${metric} (tried: ${tags.join(", ")})`;
			if (fallbackTried) note += " (companyfacts fallback also empty)";
			missing.push(note);
		}
	}
	return { metrics: result, missing };
}

export async function getFilingFacts(ticker: string, reportDate = "") {
	const facts: any = await getCompanyFacts(ticker);
	if (facts.error) return facts;
	const quarterly = await getQuarterlyFacts(facts.cik, reportDate || null);
	const out = [];
	for (const [metric, data] of Object.entries(quarterly.metrics)) {
		for (const row of data.rows) {
			const value = metric === "gaap_eps" ? Number(row.value) : Number(row.value) / 1e9;
			const unit = metric === "gaap_eps" ? "USD" : "USD_B";
			out.push({
				id: `edgar_${metric}_${row.period_end}` + (row.derived ? "_derived" : ""),
				metric,
				value,
				unit,
				period: row.period_end,
				source_tag: data.tag,
				derived: Boolean(row.derived),
				derivation: row.derivation ?? "",
				form: row.form,
				filed: row.filed,
			});
		}
	}
	return {
		ticker: facts.ticker,
		company_name: facts.company_name,
		cik: facts.cik,
		facts: out,
		missing: quarterly.missing,
	};
}
