// Frontend for the Earnings Ledger earnings briefing.
// The Orchestrator's SSE stream carries one event per pipeline
// step, and each event carries that agent's output — so this page
// renders each agent's card the moment its agent finishes, instead
// of showing one spinner until the whole briefing is done. No
// numbers are computed here; everything rendered comes from the
// stream events or the final Briefing JSON.
//
// If the Workers were created under different project names, change
// this one URL — nothing else needs to change.
const ORCHESTRATOR_URL = "https://mesh-orchestrator-proof.tejpreetsingh1988.workers.dev";

// Live log lines, kept as the detailed record under the cards.
// If the stream itself fails before any event arrives (old edge
// cache, blocked stream, anything that keeps the first byte from
// coming back), fall back to the plain POST — the briefing is the
// same either way. If the stream dies AFTER events arrived, do
// not fall back: the run is already going server-side, and a
// second POST would start a duplicate run for the same ticker.
const LOG_TEXT = {
  scout_started: (d) => `Scout: fetching filings for ${d.ticker}`,
  scout_done: (d) => `Scout: ${d.status}, ${d.facts} facts`,
  analyst_done: (d) => `Analyst: ${d.claims} claims`,
  critic_attempt: (d) => `Critic: attempt ${d.attempt} — ${d.verdict}`,
  writer_done: (d) => `Writer: story via ${d.story_model || "—"}`,
};

const $ = (id) => document.getElementById(id);

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function show(el, on) { if (el) el.hidden = !on; }

// Hotfix (Nov 4, 2026): the frontend ships in pieces — app.js can
// carry section renderers whose HTML sections land in a later
// upload (the held batches). A missing section must hide, never
// throw: every direct innerHTML/textContent write in render() and
// its section renderers goes through these two helpers, which
// no-op on a missing element. Before this, one missing section
// (b-takeaways) threw on every render and broke the whole site,
// and the throw was misreported as a lost connection.
function setHTML(el, html) { if (el) el.innerHTML = html; }
function setText(el, text) { if (el) el.textContent = text; }

function prettyMetric(m) {
  return String(m || "").replace(/_/g, " ").replace(/\b\w+/g, (w) => {
    const up = w.toUpperCase();
    return up === "GAAP" || up === "EPS" ? up : w.charAt(0).toUpperCase() + w.slice(1).toLowerCase();
  });
}

function round1(v) {
  return Number.isFinite(v) ? String(Math.round(v * 10) / 10) : "—";
}

function secs(ms) {
  if (!Number.isFinite(ms)) return "";
  return `${(ms / 1000).toFixed(1)}s`;
}

// ---- Pivot tables (Scout) and claim blocks (Analyst) ----
// Quarters become columns, one table per metric: a Revenue
// table, an EPS table, and so on — the long one-row-per-fact
// list is unreadable once a ticker has eight quarters of
// history. Nothing is computed here: every value shown is a
// streamed fact, rounded to one decimal exactly as before.
// Derived fiscal-Q4 rows (fiscal-year total minus 9-month
// year-to-date) carry a † and a footnote; the growth math
// stays with the Analyst, so the Scout table never shows a
// second, possibly disagreeing, growth figure.
function quarterLabel(period) {
  const m = /^(\d{4})-(\d{2})/.exec(String(period || ""));
  if (!m) return String(period || "");
  return `Q${Math.floor((Number(m[2]) - 1) / 3) + 1} ${m[1]}`;
}

function pivotFacts(facts) {
  const order = ["total_revenue", "operating_income", "net_income", "ebitda", "gaap_eps"];
  const groups = new Map();
  for (const f of facts || []) {
    const metric = f.metric || "unknown";
    if (!groups.has(metric)) groups.set(metric, { metric, unit: f.unit || "", byPeriod: new Map() });
    const g = groups.get(metric);
    const period = f.period || "";
    if (!g.byPeriod.has(period)) {
      g.byPeriod.set(period, {
        value: f.value, unit: f.unit || "",
        derived: String(f.id || "").endsWith("_derived"),
      });
    }
  }
  const list = [...groups.values()].map((g) => {
    const periods = [...g.byPeriod.keys()].sort();
    return { metric: g.metric, unit: g.unit, periods, cells: periods.map((p) => g.byPeriod.get(p)) };
  });
  list.sort((a, b) => {
    const ia = order.indexOf(a.metric), ib = order.indexOf(b.metric);
    return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib) || (a.metric < b.metric ? -1 : 1);
  });
  return list;
}

function metricClass(metric) {
  return metric === "total_revenue" ? "metric-revenue"
    : metric === "operating_income" ? "metric-opinc"
    : /eps/i.test(metric || "") ? "metric-eps" : "metric-other";
}

function pivotTablesHtml(facts) {
  const tables = pivotFacts(facts);
  if (!tables.length) return `<p class="agent-waiting">No facts returned.</p>`;
  const anyDerived = tables.some((t) => t.cells.some((c) => c.derived));
  const html = tables.map((t) => {
    const latest = t.periods.length - 1;
    const head = t.periods.map((p, i) =>
      `<th class="num${i === latest ? " latest-col" : ""}">${esc(quarterLabel(p))}</th>`).join("");
    const row = t.cells.map((c, i) => {
      const val = Number.isFinite(c.value) ? round1(c.value) : "—";
      const derived = c.derived
        ? '<sup title="Derived: fiscal-year total minus 9-month year-to-date">†</sup>' : "";
      const title = `${quarterLabel(t.periods[i])} · ${Number.isFinite(c.value) ? c.value : "—"} ${esc(c.unit)}${c.derived ? " · derived" : ""}`;
      return `<td class="num${i === latest ? " latest-col" : ""}" title="${esc(title)}">${val}${derived}</td>`;
    }).join("");
    return `<details class="metric-table ${metricClass(t.metric)}" open>`
      + `<summary class="metric-head"><span class="metric-dot"></span><strong>${esc(prettyMetric(t.metric))}</strong>`
      + `<span class="metric-unit">${esc(t.unit)}</span></summary>`
      + `<div class="table-wrap"><table><thead><tr><th class="metric-col-head">Value</th>${head}</tr></thead>`
      + `<tbody><tr><td class="metric-row-label">Value</td>${row}</tr></tbody></table></div></details>`;
  }).join("");
  const foot = anyDerived
    ? `<p class="metric-footnote">† Derived: fiscal-year total minus 9-month year-to-date. `
      + `Hover any value for its exact figure. Click a metric heading to collapse its table.</p>`
    : `<p class="metric-footnote">Hover any value for its exact figure. `
      + `Click a metric heading to collapse its table.</p>`;
  return html + foot;
}

function claimKind(text) {
  const t = String(text || "");
  if (/margin/i.test(t)) return "claim-margin";
  if (/eps|consensus|beat|miss/i.test(t)) return "claim-eps";
  if (/growth|yoy|qoq|year over year|quarter over quarter/i.test(t)) return "claim-growth";
  if (/price|reaction|share/i.test(t)) return "claim-price";
  return "claim-other";
}

function claimBlocksHtml(claims) {
  return (claims || []).map((c) => {
    const text = c.text || "";
    const pct = /%|percent|growth|margin|beat|miss|reaction/i.test(text) ? "%" : "";
    const value = Number.isFinite(c.value) ? round1(c.value) + pct : "—";
    return `<div class="claim ${claimKind(text)}"><div class="claim-top"><span class="claim-text">${esc(text)}</span>`
      + `<span class="claim-value">${value}</span></div>`
      + (c.derivation ? `<div class="claim-derivation">${esc(c.derivation)}</div>` : "") + `</div>`;
  }).join("");
}

// ---- Analyst table (replaces claim cards) ----
// Claims arrive as {text, value, derivation}. The table parses
// metric / period / detail OUT of the claim text for display only
// — it never recomputes a percentage. The value pill is the
// Analyst's own c.value, rounded exactly as the old cards did.
// Click a row to expand its derivation; filter + sort only
// reorder/filter the Analyst's claims, they never change one.
const analystTableData = {};
const analystTableState = {};

// Display-only cleanup for Analyst derivations: the backend prints
// raw binary floats, so a derivation can read 4.809999999999999
// where the fact is 4.81. Numbers with 7+ decimal places at or
// above 0.01 are float noise — round them to 4 decimals (trailing
// zeros stripped). Smaller values and ordinary figures (92.279,
// dates) pass through untouched. This never changes a claim
// value, only how a formula string reads.
function roundLongFloats(s) {
  return String(s).replace(/-?\d+\.\d{7,}/g, (m) => {
    const n = parseFloat(m);
    return Math.abs(n) >= 0.01 ? String(Number(n.toFixed(4))) : m;
  });
}

function parseClaim(c) {
  const text = String(c.text || "");
  const kindFull = claimKind(text);
  const kind = kindFull.replace(/^claim-/, "");
  const pct = /%|percent|growth|margin|beat|miss|reaction/i.test(text) ? "%" : "";
  const value = Number.isFinite(c.value) ? round1(c.value) + pct : "—";
  const valueNum = Number.isFinite(c.value) ? c.value : null;
  // Result number: the first % figure in the text, e.g. +14.0%.
  const resMatch = text.match(/([+-]?\d+(?:\.\d+)?%)/);
  const after = resMatch ? text.slice(text.indexOf(resMatch[0]) + resMatch[0].length) : "";
  const detailMatch = after.match(/^\s*\((.*)\)\s*$/s);
  const detail = detailMatch ? detailMatch[1] : "";
  let head = resMatch ? text.slice(0, text.indexOf(resMatch[0])).replace(/:\s*$/, "").trim() : text;
  let metric = head, period = "—";
  const paren = head.match(/^(.*?)\s*\((.*)\)\s*$/s);
  if (paren) {
    metric = paren[1].trim();
    const inside = paren[2].trim();
    // Only a date / date-range counts as a period. A long source
    // note (e.g. the EPS-vs-consensus basis note) is not a period.
    period = /\d{4}-\d{2}-\d{2}/.test(inside) ? inside : "—";
  }
  const arrow = valueNum === null ? "" : valueNum < 0 ? " ▼" : valueNum > 0 ? " ▲" : "";
  return { metric, period, detail, kind, kindFull, value, valueNum, arrow,
    derivation: roundLongFloats(String(c.derivation || "").replace(/, from facts.*$/, "")) };
}

function analystTableHtml(key, claims) {
  const st = analystTableState[key] || (analystTableState[key] = { filter: "all", sort: "original" });
  const parsed = (claims || []).map((c, i) => ({ ...parseClaim(c), _i: i }));
  const filtered = parsed.filter((p) => st.filter === "all" || p.kind === st.filter);
  const sorted = [...filtered];
  if (st.sort === "abs") sorted.sort((a, b) => Math.abs(b.valueNum || 0) - Math.abs(a.valueNum || 0));
  else if (st.sort === "metric") sorted.sort((a, b) => a.metric.localeCompare(b.metric));
  else sorted.sort((a, b) => a._i - b._i);
  const filters = [["all", "All"], ["growth", "Growth"], ["margin", "Margin"], ["eps", "EPS / consensus"], ["price", "Price"], ["other", "Other"]];
  const kindColor = { growth: "#1d4ed8", margin: "#6d28d9", eps: "#b45309", price: "#0f766e", other: "#71717a" };
  if (!parsed.length) return `<p class="agent-waiting">No claims returned.</p>`;
  // Glossary: first occurrence of each term per table render.
  const glossUsed = new Set();
  const rows = sorted.map((p) => {
    const copyLabel = `Copy claim: ${p.metric} ${p.value}`.slice(0, 80);
    return `<tr data-idx="${p._i}" title="Click to see its formula and source">`
      + `<td class="metric-cell"><span class="kind-dot" style="background:${kindColor[p.kind] || "#71717a"}"></span>${glossifyHtml(esc(p.metric), glossUsed)}</td>`
      + `<td class="period-cell">${esc(p.period)}</td>`
      + `<td class="result-cell"><span class="result-pill kind-${p.kind}${(p.valueNum || 0) < 0 ? " negative" : ""}">${esc(p.value)}${p.arrow}</span></td>`
      + `<td class="detail-cell">${glossifyHtml(esc(p.detail), glossUsed)}</td>`
      + `<td class="copy-cell"><button type="button" class="claim-copy" data-copy-idx="${p._i}" aria-label="${esc(copyLabel)}">Copy</button></td></tr>`;
  }).join("");
  return `<div class="analyst-controls" data-controls="${key}">`
    + filters.map(([f, label]) => `<button type="button" class="analyst-filter${st.filter === f ? " is-on" : ""}" data-filter="${f}">${label}</button>`).join("")
    + `<select class="analyst-sort" aria-label="Sort claims">`
    + `<option value="original"${st.sort === "original" ? " selected" : ""}>Original order</option>`
    + `<option value="abs"${st.sort === "abs" ? " selected" : ""}>Biggest % first</option>`
    + `<option value="metric"${st.sort === "metric" ? " selected" : ""}>Metric A–Z</option></select></div>`
    + `<div class="analyst-table-wrap"><table class="analyst-table"><thead><tr>`
    + `<th>Metric</th><th>Period</th><th class="num">Result</th><th>Detail</th><th aria-label="Copy claim"></th></tr></thead>`
    + `<tbody>${rows}</tbody></table></div>`
    + `<p class="analyst-note">Click a row to see its formula and source. Filters and sorting only reorder the Analyst&rsquo;s claims.</p>`;
}

// ---- Phase 1: claim popover, glossary, copy-claim, find (Features 1, 2, 3, 6, 8) ----
// The shared popover is one element appended to #briefing (which is
// position: relative). Claim rows and glossary buttons both open it;
// Esc and the close button close it (Feature 5 layering).
// Pure helpers are wrapped in [PHASE1-PURE] markers so the node
// harness can extract and test them without a DOM.

// [PHASE1-PURE:GLOSSARY]
const GLOSSARY = {
  "YoY": "Compared with the same quarter a year earlier: the Analyst pairs periods exactly 12 months apart.",
  "QoQ": "Compared with the previous quarter: the Analyst pairs periods exactly 3 months apart.",
  "Margin": "Operating income divided by revenue, for the same period only.",
  "FCF": "Free cash flow: operating cash flow minus capital expenditure, for the same period.",
  "EBITDA": "Operating income plus depreciation and amortisation, as derived from the filing (there is no GAAP EBITDA tag).",
  "Beat/miss": "Reported EPS compared with the consensus forecast on the same basis; the briefing names the basis and never mixes bases.",
  "Buybacks": "Cash the company paid to repurchase its own common stock, as reported in the filing's cash-flow statement.",
  "Guidance": "An outlook statement from the company itself; shown only as reported, never as a verified claim unless the Critic passed it as one.",
};
// [/PHASE1-PURE]

// [PHASE1-PURE:parseFactSource]
function parseFactSource(excerpt) {
  // Excerpt shapes (from the Scout's fact sources): "SEC EDGAR
  // XBRL, tag Revenues; form 10-Q." and the derived form
  // "…tag Revenues; derived Q4: FY … minus 9-month YTD …;
  // form 10-K (derived Q4)." — tag is the first "tag …" up to
  // ";", form is the first "form …" up to "." or ";".
  const s = String(excerpt || "");
  const tag = (s.match(/tag ([^;]+)/) || [])[1];
  const form = (s.match(/form ([^.;]+)/) || [])[1];
  return { tag: tag ? tag.trim() : "", form: form ? form.trim() : "" };
}
// [/PHASE1-PURE]

// [PHASE1-PURE:factSourceLine]
function factSourceLine(fact) {
  // "publisher · form · tag · period" — a line only when tag,
  // form and period are all present; otherwise the claim falls
  // back to "see Sources section below" and never guesses.
  if (!fact || !fact.period) return null;
  const { tag, form } = parseFactSource(fact.source && fact.source.excerpt);
  if (!tag || !form) return null;
  const publisher = (fact.source && fact.source.publisher) || "SEC EDGAR";
  return `${publisher} · ${form} · ${tag} · ${fact.period}`;
}
// [/PHASE1-PURE]

// [PHASE1-PURE:matchClaimSources]
function matchClaimSources(claim, facts) {
  // 1) Exact fact-id match: the Analyst embeds fact ids in the
  // RAW derivation ("…, from facts <id> and <id>."). A YoY claim
  // names exactly its two facts, so this is unambiguous.
  // 2) Fallback: facts whose period appears in the derivation.
  // Only usable when every such fact shares one metric; two
  // different metrics for the same period is ambiguous, and the
  // popover then shows the fallback line instead of guessing.
  // The market-reaction claim matches nothing (no price_reaction
  // fact exists) — the fallback line is its correct outcome.
  const derivation = String((claim && claim.derivation) || "");
  const list = Array.isArray(facts) ? facts : [];
  const byId = list.filter((f) => f && f.id && derivation.includes(f.id));
  if (byId.length) return { lines: byId.map(factSourceLine).filter(Boolean), ambiguous: false };
  const byPeriod = list.filter((f) => f && f.period && derivation.includes(f.period));
  const metrics = [...new Set(byPeriod.map((f) => f.metric))];
  if (byPeriod.length && metrics.length === 1) {
    return { lines: byPeriod.map(factSourceLine).filter(Boolean), ambiguous: false };
  }
  return { lines: [], ambiguous: byPeriod.length > 0 };
}
// [/PHASE1-PURE]

// [PHASE1-PURE:claimCopyText]
function claimCopyText(claim, parsed, sourceLines, ticker, quarter) {
  // Exact clipboard format (Feature 6 spec): the claim as the
  // table shows it (metric + display value), the display
  // derivation, one Source line (matched facts joined with "; ",
  // or the fallback), and the provenance line. Numbers are copied
  // exactly as displayed — never re-rounded here.
  const source = sourceLines.length ? sourceLines.join("; ") : "see Sources section";
  return `${parsed.metric} — ${parsed.value}\nFormula: ${parsed.derivation}\nSource: ${source}\nFrom earningsbrief.pages.dev — ${ticker} ${quarter}`;
}
// [/PHASE1-PURE]

// [PHASE1-PURE:glossifyHtml]
function glossifyHtml(escapedText, used) {
  // Wrap the FIRST occurrence of each glossary term (per render,
  // tracked in `used`) in a keyboard-activatable <button>.
  // Case-insensitive, word-boundary match on the already-escaped
  // text; the matched text keeps its original case. Terms never
  // contain one another, so wrapping one cannot create a false
  // match for a later term.
  let out = String(escapedText || "");
  for (const term of Object.keys(GLOSSARY)) {
    if (used.has(term)) continue;
    const re = new RegExp(`(?<![A-Za-z])${term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?![A-Za-z])`, "i");
    const m = out.match(re);
    if (!m) continue;
    used.add(term);
    out = out.slice(0, m.index)
      + `<button type="button" class="gloss" data-gloss-term="${term}">${m[0]}</button>`
      + out.slice(m.index + m[0].length);
  }
  return out;
}
// [/PHASE1-PURE]

// [PHASE1-PURE:levenshtein]
function levenshtein(a, b) {
  const m = a.length, n = b.length;
  if (!m) return n;
  if (!n) return m;
  let prev = Array.from({ length: n + 1 }, (_, j) => j);
  for (let i = 1; i <= m; i++) {
    const cur = [i];
    for (let j = 1; j <= n; j++) {
      cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    }
    prev = cur;
  }
  return prev[n];
}
// [/PHASE1-PURE]

// [PHASE1-PURE:didYouMean]
function didYouMean(query, directory) {
  // Feature 8: Levenshtein over the local directory only (ticker,
  // name, each name token). A candidate's score is its minimum
  // distance; sort by (distance, name A-Z). Show the top 3 only
  // when the BEST passes the gate (distance ≤ 3, or distance /
  // longer length ≤ 0.4); otherwise no suggestions at all.
  const q = String(query || "").trim().toLowerCase();
  if (!q || !Array.isArray(directory)) return [];
  const scored = [];
  for (const c of directory) {
    if (!c || !c.ticker) continue;
    const name = String(c.name || "").toLowerCase();
    const candidates = [c.ticker.toLowerCase(), name, ...name.split(/\s+/).filter(Boolean)];
    let bestD = Infinity, bestLen = 0;
    for (const s of candidates) {
      const d = levenshtein(q, s);
      if (d < bestD) { bestD = d; bestLen = Math.max(q.length, s.length); }
    }
    scored.push({ ticker: c.ticker, name: c.name || c.ticker, distance: bestD, longest: bestLen });
  }
  scored.sort((a, b) => (a.distance - b.distance) || String(a.name).localeCompare(String(b.name)));
  const best = scored[0];
  if (!best) return [];
  if (!(best.distance <= 3 || best.distance / best.longest <= 0.4)) return [];
  return scored.filter((s) => s.distance <= 3 || s.distance / s.longest <= 0.4).slice(0, 3);
}
// [/PHASE1-PURE]

// [PHASE1-PURE:countFindMatches]
function countFindMatches(query, claims, facts, storyText) {
  // Feature 3: deterministic, client-side only. Counts
  // case-insensitive substring occurrences across exactly three
  // corpora — claim rows (text + value + display derivation,
  // i.e. the fact-ids suffix stripped), Scout facts (metric +
  // period + value + publisher + excerpt), and the story text.
  // KPIs, diagram, fine print, ownership and comparison are
  // NEVER searched: separate provenance, not "this briefing".
  const q = String(query || "").toLowerCase();
  if (!q) return 0;
  const countIn = (s) => {
    const t = String(s == null ? "" : s).toLowerCase();
    return t.includes(q) ? t.split(q).length - 1 : 0;
  };
  let n = 0;
  for (const c of (claims || [])) {
    n += countIn(c.text);
    n += countIn(c.value);
    n += countIn(String(c.derivation || "").replace(/, from facts.*$/, ""));
  }
  for (const f of (facts || [])) {
    n += countIn(f.metric) + countIn(f.period) + countIn(f.value)
      + countIn(f.source && f.source.publisher) + countIn(f.source && f.source.excerpt);
  }
  n += countIn(storyText);
  return n;
}
// [/PHASE1-PURE]

let popoverEl = null;
function ensurePopover() {
  if (popoverEl) return popoverEl;
  const article = $("briefing");
  popoverEl = document.createElement("div");
  popoverEl.id = "claim-popover";
  popoverEl.className = "claim-popover";
  popoverEl.hidden = true;
  popoverEl.innerHTML = `<button type="button" class="popover-close" aria-label="Close">×</button><div class="popover-body"></div>`;
  popoverEl.querySelector(".popover-close").addEventListener("click", (e) => { e.stopPropagation(); closePopover(); });
  if (article) article.appendChild(popoverEl);
  return popoverEl;
}
function openPopover(anchorEl, html) {
  const pop = ensurePopover();
  const body = pop.querySelector(".popover-body");
  if (body) body.innerHTML = html;
  pop.hidden = false;
  // Position below the anchor, inside the briefing article.
  const article = $("briefing");
  if (anchorEl && article) {
    const a = anchorEl.getBoundingClientRect();
    const b = article.getBoundingClientRect();
    const top = Math.max(0, a.bottom - b.top + 8);
    const left = Math.max(0, Math.min(a.left - b.left, Math.max(0, b.width - pop.offsetWidth - 8)));
    pop.style.top = `${top}px`;
    pop.style.left = `${left}px`;
  }
}
function closePopover() { if (popoverEl) popoverEl.hidden = true; }
function popoverOpen() { return !!popoverEl && !popoverEl.hidden; }

function openClaimPopover(anchorEl, claim, facts) {
  // The popover is a trace, not a second verification: it shows
  // the display derivation (stripped + rounded, exactly as the
  // table shows it) and the deterministically matched source
  // lines — never a guessed source.
  const parsed = parseClaim(claim);
  const { lines } = matchClaimSources(claim, facts);
  const source = lines.length ? lines.map((l) => esc(l)).join("<br>") : "See Sources section below.";
  openPopover(anchorEl,
    `<h4>${esc(parsed.metric)}</h4>`
    + `<p class="popover-value">${esc(parsed.value)}${parsed.arrow}</p>`
    + `<p class="popover-label">Formula</p><p class="popover-formula"><code>${esc(parsed.derivation || "No derivation supplied by the Analyst.")}</code></p>`
    + `<p class="popover-label">Source</p><p class="popover-source">${source}</p>`);
}

async function copyClaim(claim, facts, ctx) {
  const parsed = parseClaim(claim);
  const { lines } = matchClaimSources(claim, facts);
  const ticker = (ctx && ctx.ticker) || (lastBriefing ? lastBriefing.ticker : "");
  const quarter = (ctx && ctx.quarter) || (lastBriefing ? lastBriefing.quarter_label : "");
  const text = claimCopyText(claim, parsed, lines, ticker, quarter);
  try { await navigator.clipboard.writeText(text); return true; }
  catch {
    try {
      const ta = document.createElement("textarea");
      ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select();
      const ok = document.execCommand("copy");
      ta.remove();
      return !!ok;
    } catch { return false; }
  }
}

function wireGlossButtons(container) {
  // Glossary buttons open the same shared popover as claim rows
  // (definition only, no numbers). Buttons are re-created on
  // every table render, so wiring happens per render.
  if (!container) return;
  container.querySelectorAll(".gloss").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const term = btn.dataset.glossTerm;
      const def = GLOSSARY[term];
      if (!def) return;
      openPopover(btn, `<h4>${esc(term)}</h4><p class="popover-def">${esc(def)}</p>`);
    });
  });
}

// ---- Feature 3: "Find in this briefing" ----
// The count is data-level (countFindMatches, pure). Navigation
// steps through DOM targets in order: claim rows (table order),
// story <mark>s (document order), then the Sources section when
// a fact matched. Clearing unwraps every <mark> exactly (each
// mark is replaced by its own text) so the story text is restored
// byte-identical. The find searches THIS briefing's rendered
// facts (renderFacts, snapshotted in render()) — not the
// module-level lastScoutFacts, which a comparison run overwrites
// with the second company's facts.
let findHits = [];
let findIdx = -1;
function clearFindMarks() {
  document.querySelectorAll("#b-story mark.find-mark").forEach((m) => {
    m.replaceWith(document.createTextNode(m.textContent));
  });
  document.querySelectorAll(".find-hit").forEach((el) => el.classList.remove("find-hit"));
}
function resetFind() {
  clearFindMarks();
  findHits = [];
  findIdx = -1;
  const input = $("briefing-find-input");
  if (input) input.value = "";
  const countEl = $("briefing-find-count");
  if (countEl) countEl.textContent = "";
}
function wrapStoryMatches(el, ql) {
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  for (const node of nodes) {
    const text = node.textContent;
    const lower = text.toLowerCase();
    let pos = 0, idx;
    const frag = document.createDocumentFragment();
    let found = false;
    while ((idx = lower.indexOf(ql, pos)) !== -1) {
      found = true;
      if (idx > pos) frag.appendChild(document.createTextNode(text.slice(pos, idx)));
      const mark = document.createElement("mark");
      mark.className = "find-mark";
      mark.textContent = text.slice(idx, idx + ql.length);
      frag.appendChild(mark);
      pos = idx + ql.length;
    }
    if (found) {
      if (pos < text.length) frag.appendChild(document.createTextNode(text.slice(pos)));
      node.replaceWith(frag);
    }
  }
}
function highlightFindHit() {
  document.querySelectorAll(".find-hit").forEach((el) => el.classList.remove("find-hit"));
  const el = findHits[findIdx];
  if (!el) return;
  el.classList.add("find-hit");
  el.scrollIntoView({ block: "nearest", behavior: "smooth" });
}
function runFind() {
  const input = $("briefing-find-input");
  const q = input ? input.value.trim() : "";
  clearFindMarks();
  findHits = [];
  findIdx = -1;
  const countEl = $("briefing-find-count");
  if (!q) { if (countEl) countEl.textContent = ""; return; }
  const storyEl = $("b-story");
  const storyText = storyEl ? storyEl.textContent : "";
  const n = countFindMatches(q, lastAnalystClaims, renderFacts, storyText);
  if (countEl) countEl.textContent = n === 1 ? "1 match" : `${n} matches`;
  if (!n) return;
  const ql = q.toLowerCase();
  const table = $("b-table");
  if (table) {
    table.querySelectorAll("tbody tr[data-idx]").forEach((row) => {
      const idx = Number(row.dataset.idx);
      const c = lastAnalystClaims[idx];
      if (!c) return;
      const hay = `${c.text} ${c.value} ${String(c.derivation || "").replace(/, from facts.*$/, "")}`.toLowerCase();
      if (hay.includes(ql)) findHits.push(row);
    });
  }
  if (storyEl && storyText.toLowerCase().includes(ql)) {
    wrapStoryMatches(storyEl, ql);
    storyEl.querySelectorAll("mark.find-mark").forEach((m) => findHits.push(m));
  }
  const factHit = (renderFacts || []).some((f) =>
    [f.metric, f.period, f.value, f.source && f.source.publisher, f.source && f.source.excerpt]
      .some((v) => String(v == null ? "" : v).toLowerCase().includes(ql)));
  if (factHit) {
    const sec = $("b-sources");
    if (sec) findHits.push(sec.closest("section") || sec);
  }
  if (findHits.length) { findIdx = 0; highlightFindHit(); }
}
function stepFind(dir) {
  if (!findHits.length) return;
  findIdx = (findIdx + dir + findHits.length) % findHits.length;
  highlightFindHit();
}

const analystTableFacts = {};
const analystTableContext = {};
function renderAnalyst(key, claims, el, noteHtml, facts, ctx) {
  analystTableData[key] = claims || [];
  // The popover matches a row's claim against the facts that
  // produced IT — stored per table, so a comparison run (which
  // overwrites the module-level lastScoutFacts with the second
  // company's facts) can never make the base table cite the
  // wrong filing. Filter/sort re-renders reuse the stored facts.
  analystTableFacts[key] = facts || analystTableFacts[key] || lastScoutFacts || [];
  if (ctx) analystTableContext[key] = ctx;
  if (!el) return;
  el.innerHTML = (noteHtml || "") + analystTableHtml(key, analystTableData[key]);
  const controls = el.querySelector(`[data-controls="${key}"]`);
  if (controls) {
    controls.querySelectorAll("[data-filter]").forEach((btn) => {
      btn.addEventListener("click", () => {
        analystTableState[key].filter = btn.dataset.filter;
        renderAnalyst(key, analystTableData[key], el, noteHtml, analystTableFacts[key], analystTableContext[key]);
      });
    });
    const sel = controls.querySelector(".analyst-sort");
    if (sel) sel.addEventListener("change", () => {
      analystTableState[key].sort = sel.value;
      renderAnalyst(key, analystTableData[key], el, noteHtml, analystTableFacts[key], analystTableContext[key]);
    });
  }
  wireGlossButtons(el);
  el.querySelectorAll("tbody tr[data-idx]").forEach((row) => {
    row.addEventListener("click", (e) => {
      e.stopPropagation();
      const idx = Number(row.dataset.idx);
      const claim = (analystTableData[key] || [])[idx];
      if (!claim) return;
      openClaimPopover(row, claim, analystTableFacts[key]);
    });
  });
  el.querySelectorAll(".claim-copy").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const idx = Number(btn.dataset.copyIdx);
      const claim = (analystTableData[key] || [])[idx];
      if (!claim) return;
      const ok = await copyClaim(claim, analystTableFacts[key], analystTableContext[key]);
      const orig = btn.textContent;
      btn.textContent = ok ? "Copied" : "Copy failed";
      setTimeout(() => { btn.textContent = orig; }, 2000);
    });
  });
}

// ---- Charts + glance + handover loop (right/left rails) ----
// All chart data comes from streamed Scout facts / Analyst claims
// stored below. Nothing is invented here: a chart with no source
// data stays empty with its placeholder text.
// Theme-aware chart colours (Batch 16): canvas cannot resolve CSS
// variables, so dark variants are picked in JS from data-theme.
function themeColor(light, dark) {
  return document.documentElement.dataset.theme === "dark" ? dark : light;
}
let lastScoutFacts = [];
let lastAnalystClaims = [];
let renderFacts = [];
const chartInstances = {};

function destroyChart(id) {
  if (chartInstances[id]) { try { chartInstances[id].destroy(); } catch (e) {} delete chartInstances[id]; }
}
function setChartEmpty(id, showEmpty) {
  const el = $(`chart-${id}-empty`);
  if (el) el.hidden = !showEmpty;
}
function makeChart(id, type, labels, datasets, opts) {
  if (typeof Chart === "undefined") return null;
  const canvas = $(`chart-${id}`);
  if (!canvas) return null;
  destroyChart(id);
  const chart = new Chart(canvas, { type, data: { labels, datasets },
    options: { responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { font: { size: 11 } } },
        tooltip: { titleFont: { size: 12 }, bodyFont: { size: 12 } } },
      scales: type === "doughnut" ? {} : { y: { ticks: { font: { size: 11 } } }, x: { ticks: { font: { size: 11 } } } },
      ...(opts || {}) } });
  chartInstances[id] = chart;
  return chart;
}
// Trend chart metric (Batch 15): the switcher choice persists across
// briefings — it is a viewing preference, not per-briefing state.
// A briefing without the chosen series shows that metric's empty
// note rather than silently falling back to revenue.
let trendMetric = "total_revenue";

function updateTrendChart() {
  const tables = pivotFacts(lastScoutFacts);
  const table = tables.find((t) => t.metric === trendMetric);
  const label = { total_revenue: "Revenue", operating_income: "Operating income",
    net_income: "Net income", ebitda: "EBITDA" }[trendMetric] || "Revenue";
  if (!table || !table.periods.length) {
    destroyChart("trend"); setChartEmpty("trend", true);
    const note = $("chart-trend-empty");
    if (note) note.textContent = `No ${label.toLowerCase()} series in this briefing's facts.`;
    setChartsVisible();
    return;
  }
  const labels = table.periods.map(quarterLabel);
  const data = table.cells.map((c) => Number.isFinite(c.value) ? c.value : null);
  setChartEmpty("trend", false);
  makeChart("trend", "bar", labels, [{ label: `${label} (${table.unit || ""})`.trim(), data,
    backgroundColor: labels.map((_, i) => i === labels.length - 1 ? themeColor("#1d4ed8", "#60a5fa") : "#93c5fd"),
    borderRadius: 6 }]);
  setChartsVisible();
}
function updateGrowthChart() {
  const rows = (lastAnalystClaims || []).map(parseClaim)
    .filter((p) => /yoy/i.test(p.metric) && p.kind !== "other" && p.valueNum !== null);
  if (!rows.length) {
    destroyChart("growth"); setChartEmpty("growth", true);
    const note = $("chart-growth-empty");
    if (note) note.textContent = "No YoY claims in this briefing.";
    return;
  }
  setChartEmpty("growth", false);
  const colors = { growth: themeColor("#1d4ed8", "#60a5fa"), margin: themeColor("#6d28d9", "#a78bfa"), eps: themeColor("#b45309", "#fbbf24"), price: themeColor("#0f766e", "#2dd4bf"), other: themeColor("#71717a", "#a1a1aa") };
  makeChart("growth", "bar", rows.map((r) => r.metric.replace(/\s*YoY\s*/i, "")),
    [{ label: "YoY %", data: rows.map((r) => r.valueNum),
      backgroundColor: rows.map((r) => colors[r.kind] || "#71717a"), borderRadius: 6 }]);
}
function updateEpsAndMarginCharts() {
  const parsed = (lastAnalystClaims || []).map(parseClaim);
  const epsClaim = parsed.find((p) => /consensus/i.test(p.metric));
  if (epsClaim) {
    const m = epsClaim.detail.match(/\$?([\d.]+)\s*vs\s*\$?([\d.]+)/);
    if (m) {
      setChartEmpty("eps", false);
      makeChart("eps", "bar", ["Reported", "Forecast"],
        [{ label: "EPS ($)", data: [Number(m[1]), Number(m[2])],
          backgroundColor: [themeColor("#b45309", "#fbbf24"), "#fde68a"], borderRadius: 6 }]);
    }
  } else { destroyChart("eps"); setChartEmpty("eps", true); }
  const margin = parsed.find((p) => p.kind === "margin");
  if (margin && margin.valueNum !== null) {
    setChartEmpty("margin", false);
    makeChart("margin", "doughnut", ["Operating margin", "Rest"],
      [{ data: [margin.valueNum, Math.max(0, 100 - margin.valueNum)],
        backgroundColor: [themeColor("#6d28d9", "#a78bfa"), themeColor("#e4e4e7", "#3f3f46")], borderWidth: 0 }]);
  } else { destroyChart("margin"); setChartEmpty("margin", true); }
}
function updateGlance(quarterLabelText) {
  const tables = pivotFacts(lastScoutFacts);
  const rev = tables.find((t) => t.metric === "total_revenue");
  const latest = rev && rev.periods.length ? rev.periods[rev.periods.length - 1] : null;
  const latestCell = latest ? rev.cells[rev.periods.indexOf(latest)] : null;
  if ($("glance-quarter")) $("glance-quarter").textContent = quarterLabelText || (latest ? quarterLabel(latest) : "—");
  if ($("glance-revenue")) $("glance-revenue").textContent = latestCell && Number.isFinite(latestCell.value)
    ? `${round1(latestCell.value)} ${latestCell.unit || ""}`.trim() : "—";
  const parsed = (lastAnalystClaims || []).map(parseClaim);
  const margin = parsed.find((p) => p.kind === "margin");
  if ($("glance-margin")) $("glance-margin").textContent = margin ? margin.value : "—";
  const epsClaim = parsed.find((p) => /consensus/i.test(p.metric));
  if ($("glance-eps")) $("glance-eps").textContent = epsClaim ? `${epsClaim.value} (${epsClaim.detail})` : "—";
}
function updateAllCharts(quarterLabelText) {
  updateTrendChart(); updateGrowthChart(); updateEpsAndMarginCharts(); updateGlance(quarterLabelText);
  setChartsVisible();
}
function clearCharts() {
  ["trend", "growth", "eps", "margin"].forEach((id) => { destroyChart(id); setChartEmpty(id, true); });
  lastScoutFacts = []; lastAnalystClaims = [];
  ["glance-quarter", "glance-revenue", "glance-margin", "glance-eps"].forEach((id) => { const el = $(id); if (el) el.textContent = "—"; });
  setChartsVisible();
}

// Progressive chart reveal: the rail holds one quiet note until
// data exists, then shows exactly the cards its data supports.
function setChartsVisible() {
  const rail = $("charts-rail");
  if (!rail) return;
  rail.classList.toggle("has-facts", (lastScoutFacts || []).length > 0);
  rail.classList.toggle("has-claims", (lastAnalystClaims || []).length > 0);
}

const LOOP_ORDER = ["scout", "analyst", "critic", "writer", "conductor"];
const LOOP_LABEL = { scout: "Scout", analyst: "Analyst", critic: "Critic", writer: "Writer", conductor: "Conductor" };
const RAIL_CONNS = [
  ["scout", "analyst", "rail-conn-scout-analyst"],
  ["analyst", "critic", "rail-conn-analyst-critic"],
  ["critic", "writer", "rail-conn-critic-writer"],
];
// The rail is a straight line, not a loop: exactly one step is
// active, earlier steps are done, and a segment fills only when
// that handover really happened. "conductor" means the whole
// line is done (briefing assembled or pipeline stopped).
function setLoop(agent, statusText) {
  const activeIdx = agent ? LOOP_ORDER.indexOf(agent) : -1;
  document.querySelectorAll(".baton-step").forEach((step) => {
    const a = step.dataset.agent;
    const idx = LOOP_ORDER.indexOf(a);
    const isDone = activeIdx >= 0 && idx < activeIdx;
    const isActive = a === agent;
    step.classList.toggle("is-active", isActive);
    step.classList.toggle("is-done", isDone);
    const node = step.querySelector(".baton-node");
    if (node) node.textContent = isDone ? "✓" : (node.dataset.letter || "");
  });
  RAIL_CONNS.forEach(([from, , id]) => {
    const el = $(id);
    if (el) el.classList.toggle("is-filled", activeIdx >= 0 && LOOP_ORDER.indexOf(from) < activeIdx);
  });
  const status = $("loop-status");
  if (status) status.textContent = statusText || (agent ? `${LOOP_LABEL[agent]} has the baton.` : "No run yet. Pick a company to start the pipeline.");
}

// One handover line sits between two ledger rows and is filled
// only when that handover really happened — never in advance.
function setHandoverLine(key, text) {
  const el = $(`handover-${key}`);
  if (!el) return;
  el.textContent = text;
  el.hidden = false;
}

function tookText(durationMs) {
  return durationMs ? ` · took ${secs(durationMs)}` : "";
}
function addHandover(text) {
  const feed = $("handover-feed");
  if (!feed) return;
  const time = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const li = document.createElement("li");
  const t = document.createElement("time");
  t.textContent = time;
  li.append(t, document.createTextNode(` ${text}`));
  feed.prepend(li);
  while (feed.children.length > 8) feed.removeChild(feed.lastChild);
}
function initBackground() {
  // tsParticles slim bundle (MIT). If the CDN is blocked, the CSS
  // mesh blobs behind it still give the page its colour — the
  // briefing never depends on the background library.
  if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  try {
    const tp = window.tsParticles;
    if (!tp || typeof tp.load !== "function") return;
    tp.load({ id: "bg-particles", options: {
      fpsLimit: 60, background: { color: { value: "transparent" } },
      particles: { number: { value: 55, density: { enable: true, area: 900 } },
        color: { value: ["#a1a1aa"] },
        links: { enable: true, color: "#d4d4d8", distance: 140, opacity: 0.5 },
        move: { enable: true, speed: 0.6, direction: "none", outModes: "out" },
        opacity: { value: 0.55 }, size: { value: { min: 2, max: 4 } } },
      detectRetina: true } });
  } catch (e) { /* background is decorative; never break the page */ }
}

function storyHtml(text) {
  // LLM stories use markdown bold for lead-ins. The page renders
  // plain text, so convert matched **bold** to <strong> (after
  // escaping, so this cannot inject markup) and drop any stray
  // markers instead of showing literal asterisks.
  return String(text || "").split(/\n\n+/).map((p) => {
    const html = esc(p).replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>").replace(/\*\*/g, "");
    return `<p>${html}</p>`;
  }).join("");
}

// ---- Agent cards ----

const AGENT_ORDER = ["scout", "analyst", "critic", "writer"];
let runStartedAt = 0;
let elapsedTimer = null;
let analystRuns = 0;
let workingAgent = null;

function card(agent) { return $(`card-${agent}`); }

function setStatus(agent, state, timeText) {
  const el = card(agent);
  if (!el) return;
  el.dataset.state = state;
  const pill = el.querySelector("[data-status]");
  if (pill) pill.textContent = state === "done" ? "Done"
    : state === "working" ? "Working"
    : state === "failed" ? "Failed"
    : state === "revising" ? "Revising"
    : state === "queued" ? "Queued"
    : state === "gate" ? "Stopped by check"
    : state === "skipped" ? "Skipped"
    : state === "paused" ? "Paused"
    : "Waiting";
  const t = el.querySelector("[data-time]");
  if (t) t.textContent = timeText || "";
}

function setBody(agent, html) {
  const el = card(agent);
  const body = el && el.querySelector("[data-body]");
  if (body) body.innerHTML = html;
}

function resetCards() {
  AGENT_ORDER.forEach((a) => {
    setStatus(a, "queued", "");
    const waiting = {
      scout: "Queued — runs first.",
      analyst: "Queued — runs after Scout.",
      critic: "Queued — runs after Analyst.",
      writer: "Queued — runs after Critic passes.",
    }[a];
    setBody(a, `<p class="agent-waiting">${waiting}</p>`);
  });
  analystRuns = 0;
  workingAgent = null;
  const feed = $("handover-feed");
  if (feed) feed.innerHTML = "";
  document.querySelectorAll(".handover-line").forEach((el) => { el.hidden = true; el.textContent = ""; });
  const strip = $("conductor-strip");
  if (strip) strip.classList.remove("is-alert");
  const retry = $("error-retry");
  if (retry) retry.hidden = true;
  setLoop(null, "Starting the pipeline.");
  clearCharts();
}

function setConductor(text, detail) {
  $("conductor-status").textContent = text;
  if (detail !== undefined) $("conductor-detail").textContent = detail;
}

function startElapsed() {
  stopElapsed();
  runStartedAt = Date.now();
  $("conductor-time").textContent = "0.0s";
  elapsedTimer = setInterval(() => {
    $("conductor-time").textContent = `${((Date.now() - runStartedAt) / 1000).toFixed(1)}s`;
  }, 500);
}

function stopElapsed(finalText) {
  if (elapsedTimer) clearInterval(elapsedTimer);
  elapsedTimer = null;
  if (finalText !== undefined) $("conductor-time").textContent = finalText;
}

function issueText(issue) {
  if (typeof issue === "string") return issue;
  if (issue && typeof issue === "object") {
    return issue.issue || issue.message || issue.detail || JSON.stringify(issue);
  }
  return String(issue ?? "");
}

function onStreamEvent(ev, ticker) {
  const name = ev.event;
  // Batch 31: the run's id, carried by the first event. The
  // retry button after a break resumes this run instead of
  // restarting it; a fresh run's run_started overwrites it.
  if (name === "run_started") {
    lastRunId = ev.run_id || "";
    return;
  }
  if (name === "scout_started") {
    setConductor("Now: Scout — fetching filings", "Step 1 of 4 · Next: Analyst · Usually 30–90s");
    setStatus("scout", "working", "");
    workingAgent = "scout";
    setLoop("scout", "Scout has the baton — fetching filings.");
    addHandover("Conductor → Scout: fetch filings");
    return;
  }
  if (name === "scout_done") {
    const facts = ev.fact_list || [];
    lastScoutFacts = facts;
    currentQuarterLabel = ev.quarter_label || "";
    updateTrendChart();
    const publishers = [...new Set(facts.map((f) => (f.source && f.source.publisher) || "").filter(Boolean))];
    setBody("scout",
      `<p class="agent-filing">${esc(ev.company_name || ticker)} — ${esc(ev.quarter_label || "")} — `
      + `${esc(ev.status || "")} · Transcript: ${esc(ev.transcript_status || "unknown")}</p>`
      + pivotTablesHtml(facts)
      + (publishers.length ? `<p class="metric-footnote">Sources: ${esc(publishers.join(", "))}.</p>` : ""));
    setStatus("scout", "done", ev.duration_ms ? `took ${secs(ev.duration_ms)}` : "");
    setConductor("Now: Analyst — computing claims", "Step 2 of 4 · Next: Critic");
    setStatus("analyst", "working", "");
    workingAgent = "analyst";
    setLoop("analyst", `Scout handed over ${facts.length} facts.`);
    setHandoverLine("scout-analyst", `Scout → Analyst · ${facts.length} facts${tookText(ev.duration_ms)}`);
    addHandover(`Scout → Analyst: ${facts.length} facts`);
    return;
  }
  if (name === "analyst_done") {
    analystRuns += 1;
    const claims = ev.claim_list || [];
    lastAnalystClaims = claims;
    const note = analystRuns > 1
      ? `<p class="agent-note">Revised after Critic feedback.</p>` : "";
    const analystEl = card("analyst") && card("analyst").querySelector("[data-body]");
    renderAnalyst("analyst", claims, analystEl, note, lastScoutFacts, { ticker: currentTicker, quarter: currentQuarterLabel });
    updateAllCharts();
    setStatus("analyst", "done", ev.duration_ms ? `took ${secs(ev.duration_ms)}` : "");
    setConductor("Now: Critic — re-checking every number", "Step 3 of 4 · Next: Writer");
    setStatus("critic", "working", "");
    workingAgent = "critic";
    setLoop("critic", `Analyst handed over ${claims.length} claims.`);
    setHandoverLine("analyst-critic", `Analyst → Critic · ${claims.length} claims${tookText(ev.duration_ms)}`);
    addHandover(`Analyst → Critic: ${claims.length} claims`);
    return;
  }
  if (name === "critic_attempt") {
    const issues = ev.issue_list || [];
    if (ev.verdict === "PASS") {
      const body = issues.length
        ? `<ul class="list">${issues.map((i) => `<li>${esc(issueText(i))}</li>`).join("")}</ul>`
        : `<p class="agent-pass">No issues — every claim re-checked and approved.</p>`;
      setBody("critic", body);
      setStatus("critic", "done", ev.duration_ms ? `took ${secs(ev.duration_ms)}` : "");
      setConductor("Now: Writer — writing the story", "Step 4 of 4 · Next: briefing");
      setStatus("writer", "working", "");
      workingAgent = "writer";
      setLoop("writer", "Critic passed — Writer has the baton.");
      setHandoverLine("critic-writer", `Critic → Writer · PASS${tookText(ev.duration_ms)}`);
      addHandover("Critic → Writer: PASS");
    } else {
      setBody("critic",
        `<p class="agent-fail">Attempt ${ev.attempt} — FAIL. Analyst is revising.</p>`
        + `<ul class="list">${issues.map((i) => `<li>${esc(issueText(i))}</li>`).join("")}</ul>`);
      setStatus("critic", "revising", "");
      setStatus("analyst", "working", "");
      workingAgent = "analyst";
      setLoop("analyst", "Critic failed the claims — Analyst is revising.");
      setHandoverLine("analyst-critic", `Critic → Analyst · FAIL, revising (attempt ${ev.attempt})`);
      addHandover("Critic → Analyst: FAIL, revising");
    }
    return;
  }
  if (name === "writer_done") {
    setBody("writer",
      `<div class="story">${storyHtml(ev.story || "")}</div>`
      + `<p class="meta">Story written via: ${esc(ev.story_model || "—")}</p>`);
    setStatus("writer", "done", ev.duration_ms ? `took ${secs(ev.duration_ms)}` : "");
    setConductor("Now: Conductor — assembling the briefing", "Step 4 of 4 · Almost done");
    workingAgent = null;
    setLoop("conductor", "Writer handed the story back to the Conductor.");
    setHandoverLine("writer-conductor", `Writer → Conductor · story ready${tookText(ev.duration_ms)}`);
    addHandover("Writer → Conductor: story ready");
  }
}

// ---- Live log ----

let logLines = [];
let running = false;

function addLog(text) {
  const time = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  logLines.push(`${time} ${text}`);
  const li = document.createElement("li");
  const t = document.createElement("time");
  t.textContent = time;
  li.append(t, document.createTextNode(` ${text}`));
  $("log-list").append(li);
  $("log-now").textContent = `Now: ${text}`;
}

// Terminal Critic refusal (attempt 2 FAIL): the Critic takes
// the gate state (amber — a check stopped the run, not a crash),
// the Writer is marked skipped (it never ran), the Analyst keeps
// its done state (it did the work; its claims were refused), and
// the banner says plainly that nothing was published.
function showCriticFail(ticker, issues) {
  setBody("critic",
    `<p class="agent-fail">Final attempt — FAIL. No briefing published.</p>`
    + (issues.length
      ? `<ul class="list">${issues.map((i) => `<li>${esc(issueText(i))}</li>`).join("")}</ul>`
      : ""));
  setStatus("critic", "gate", "");
  setStatus("analyst", "done", "");
  setStatus("writer", "skipped", "");
  workingAgent = null;
  setConductor("Stopped by check — Critic refused to publish", "The gate worked, not a crash · No briefing published");
  setLoop("critic", "Critic refused to publish — Writer skipped.");
  setHandoverLine("critic-writer", "Critic → Writer · blocked — gate refused to publish");
  addHandover("Critic → Conductor: FAIL, briefing stopped");
  const strip = $("conductor-strip");
  if (strip) strip.classList.add("is-alert");
  $("error-msg").textContent = `No briefing was published for ${ticker}: the Critic found problems `
    + `in the numbers (listed on the Critic card) and refused to approve them. That refusal is `
    + `the gate working, not a crash. Try another company, or try this one again later.`;
  show($("error"), true);
}

function showBriefingError(ticker, message, opts = {}) {
  $("error-msg").textContent = `Could not build a briefing for ${ticker}.\n${message}\n\n`
    + `If this says Critic FAIL, the agents disagreed about a number and refused to publish — `
    + `that refusal is the product working. If it says NOT_REPORTED_YET, the company has not `
    + `reported its most recent quarter yet. Otherwise, try again in a minute.`;
  // Retry only when re-running could change the outcome: a broken
  // connection, not a server verdict (FAIL / NOT_REPORTED_YET
  // would just reproduce itself).
  const retry = $("error-retry");
  if (retry) retry.hidden = !opts.retry;
  show($("error"), true);
}

// Returns true when the stream spoke (briefing rendered or an
// error event shown) and false when it failed before any event,
// which is the only case that falls back to POST.
async function runStream(ticker, quarter = "", onBriefing = null, resumeRunId = "") {
  const q = quarter ? `&quarter=${encodeURIComponent(quarter)}` : "";
  const r = resumeRunId ? `&resume_run_id=${encodeURIComponent(resumeRunId)}` : "";
  const resp = await fetch(`${ORCHESTRATOR_URL}/tasks/stream?ticker=${encodeURIComponent(ticker)}${q}${r}`);
  if (!resp.ok || !resp.body) return false;
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let sawEvent = false;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buffer.indexOf("\n\n")) !== -1) {
        const block = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        for (const line of block.split("\n")) {
          if (!line.startsWith("data: ")) continue;
          sawEvent = true;
          const ev = JSON.parse(line.slice(6));
          if (ev.event === "briefing") {
            // A render failure is a display failure, not a lost
            // connection: mark it so runStream's catch shows the
            // real error instead of the connection-lost copy.
            try { render(ev.briefing); } catch (e) { const err = new Error("Could not display the briefing: " + (e && e.message ? e.message : String(e))); err.isDisplayError = true; throw err; }
            saveBriefingCache(ev.briefing, quarter);
            renderRecentBriefings();
            if (onBriefing) onBriefing(ev.briefing);
            const total = ((Date.now() - runStartedAt) / 1000).toFixed(1);
            stopElapsed(`Done in ${total}s`);
            setCheckedLine(total);
            setConductor("Done — briefing ready", `Ready in ${total}s · 4 of 4 steps`);
            setLoop("conductor", `Briefing complete in ${total}s.`);
            setHandoverLine("writer-conductor", `Writer → Conductor · briefing complete in ${total}s`);
            addHandover("Conductor: briefing complete");
            return true;
          }
          if (ev.event === "error") {
            stopElapsed();
            // Batch 31: the run id is unknown (never started, or
            // its log is gone) — fall back to a fresh run once,
            // instead of showing a dead end. The fresh call has
            // no resume id, so this cannot loop.
            if (ev.code === "unknown_run" && resumeRunId) {
              lastRunId = "";
              return runStream(ticker, quarter, onBriefing);
            }
            if (ev.verdict === "FAIL") {
              showCriticFail(ticker, ev.issues || []);
            } else {
              if (workingAgent) setStatus(workingAgent, "failed", "");
              setConductor("Pipeline stopped with an error", "The server reported this run failed");
              showBriefingError(ticker, ev.error || "Stream failed");
            }
            return true;
          }
          onStreamEvent(ev, ticker);
          const text = LOG_TEXT[ev.event];
          if (text) addLog(text(ev));
        }
      }
    }
  } catch (e) {
    // A display failure is not a lost connection: render() threw
    // while drawing a briefing that fully arrived (hotfix Nov 4,
    // 2026 — the missing-section throw). Show the real error and
    // do not offer a resume, which would only reproduce it.
    if (e && e.isDisplayError) {
      stopElapsed();
      showBriefingError(ticker, e.message, { retry: false });
      return true;
    }
    // Stream broke mid-run: this is a lost connection, NOT a job
    // failure. Batch 31: the run itself is dead (the server
    // cancels its pipeline task on disconnect), but its
    // checkpoint survives — the ledger stays frozen and the
    // button resumes from the last finished stage instead of
    // restarting. No duplicate POST and no automatic retry: the
    // resume is the user's explicit choice.
    if (sawEvent) {
      stopElapsed();
      // Frozen, not failed: the working step pauses (its dot stops
      // pulsing, because only [data-state="working"] animates).
      if (workingAgent) setStatus(workingAgent, "paused", "");
      setConductor("Connection lost — live stream stopped", "Run frozen at its last checkpoint · Resume continues from there");
      const strip = $("conductor-strip");
      if (strip) strip.classList.add("is-alert");
      setRetryLabel();
      showBriefingError(ticker, `Live log stopped mid-run: ${e.message}`, { retry: true });
      return true;
    }
    return false;
  }
  // Stream ended without a briefing or an error event: if it
  // spoke at all, that is the outcome; otherwise fall back.
  if (sawEvent) {
    stopElapsed();
    if (workingAgent) setStatus(workingAgent, "paused", "");
    setConductor("Connection lost — live stream ended early", "Run frozen at its last checkpoint · Resume continues from there");
    const strip = $("conductor-strip");
    if (strip) strip.classList.add("is-alert");
    setRetryLabel();
    showBriefingError(ticker, "Live log ended before the briefing arrived", { retry: true });
    return true;
  }
  return false;
}

async function runPost(ticker, quarter = "", onBriefing = null) {
  const payload = { ticker };
  if (quarter) payload.quarter = quarter;
  const resp = await fetch(`${ORCHESTRATOR_URL}/tasks/send`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await resp.json();
  if (!resp.ok || body.state !== "completed") {
    throw new Error(body.error || body.result || `Request failed (HTTP ${resp.status})`);
  }
  render(body.result);
  setCheckedLine(((Date.now() - runStartedAt) / 1000).toFixed(1));
  saveBriefingCache(body.result, quarter);
  renderRecentBriefings();
  if (onBriefing) onBriefing(body.result);
}

// The ticker box is gone (Nov 2, 2026): the company search is
// the only search. The briefing's ticker lives here, set by the
// suggestion click that starts the run.
let currentTicker = "";
let currentQuarter = "";
let currentQuarterLabel = "";

// Batch 31: the in-flight (or just-broken) stream's run id,
// set by its run_started event. The retry button after a break
// resumes this run; a fresh run clears it first, so a later
// break never resumes a stale run.
let lastRunId = "";
function setRetryLabel() {
  const retry = $("error-retry");
  if (retry) retry.textContent = lastRunId ? "Resume run" : "Run again";
}

// Repeat-briefing cache: a completed briefing (plus the Scout
// facts its charts need) is saved per ticker in localStorage.
// A repeat run renders it instantly with a banner naming the
// saved time and quarter — never silently stale — and Refresh
// deletes the entry and re-runs the live pipeline.
function cacheKey(ticker, quarter) { return `ame_briefing_${ticker}_${quarter || "LATEST"}`; }
function legacyCacheKey(ticker) { return `ame_briefing_${ticker}`; }
function readBriefingCache(ticker, quarter) {
  try {
    // One-time migration: entries saved before quarters existed
    // live under the legacy key; a latest-quarter read falls back
    // to them, and the next save writes the new key.
    const raw = localStorage.getItem(cacheKey(ticker, quarter))
      || (!quarter ? localStorage.getItem(legacyCacheKey(ticker)) : null);
    if (!raw) return null;
    const entry = JSON.parse(raw);
    if (!entry || !entry.briefing || !entry.savedAt) return null;
    return entry;
  } catch { return null; }
}
function saveBriefingCache(briefing, quarter) {
  try {
    localStorage.setItem(cacheKey(briefing.ticker, quarter), JSON.stringify({
      briefing, facts: lastScoutFacts || [], savedAt: Date.now(),
    }));
  } catch { /* cache is best-effort; a full store never breaks a run */ }
}
function hideCacheBanner() {
  const b = $("cache-banner");
  if (b) show(b, false);
}
function showCacheBanner(ticker, cached, quarter) {
  let banner = $("cache-banner");
  if (!banner) {
    banner = document.createElement("div");
    banner.id = "cache-banner";
    banner.className = "cache-banner";
    $("briefing").parentNode.insertBefore(banner, $("briefing"));
  }
  const when = new Date(cached.savedAt).toLocaleString();
  const label = cached.briefing.quarter_label || "";
  banner.innerHTML = `Showing a briefing saved ${esc(when)} for ${esc(label)}. `
    + `<button type="button" class="btn-secondary" id="cache-refresh">Refresh for latest data</button>`;
  banner.querySelector("#cache-refresh").addEventListener("click", () => {
    try {
      localStorage.removeItem(cacheKey(ticker, quarter));
      if (!quarter) localStorage.removeItem(legacyCacheKey(ticker));
    } catch {}
    hideCacheBanner();
    getBriefing(ticker, quarter);
  });
  show(banner, true);
}

function setQuarterButtonsDisabled(disabled) {
  document.querySelectorAll("#quarter-picker button").forEach((b) => { b.disabled = disabled; });
}

async function getBriefing(ticker, quarter = "", onDone = null, resumeRunId = "") {
  ticker = String(ticker || "").trim().toUpperCase();
  quarter = String(quarter || "").trim();
  if (!/^Q[1-4] \d{4}$/.test(quarter) && !/^quarter ended \d{4}-\d{2}-\d{2}$/.test(quarter)) quarter = "";
  if (!ticker || running) return;
  // A fresh run clears any broken run's id (a resume keeps it,
  // so a second break resumes the same run again).
  if (!resumeRunId) lastRunId = "";
  // A new run replaces any comparison view; a compare run
  // rebuilds it through onDone after its briefing renders.
  show($("comparison"), false);
  // Shareable link: the URL always names the briefing being run,
  // plus its quarter when it is not the latest.
  try {
    const url = new URL(location.href);
    url.searchParams.set("ticker", ticker);
    if (quarter) url.searchParams.set("quarter", quarter);
    else url.searchParams.delete("quarter");
    history.replaceState(null, "", url);
  } catch { /* URL sharing is best-effort */ }
  currentTicker = ticker;
  currentQuarter = quarter;
  // Repeat run: serve the saved briefing instantly, with its banner.
  // No pipeline, no agent cards, no log — the banner is the whole story.
  const cached = readBriefingCache(ticker, quarter);
  if (cached) {
    lastScoutFacts = cached.facts || [];
    try { render(cached.briefing); } catch (e) { showBriefingError(ticker, "Could not display the saved briefing: " + (e && e.message ? e.message : String(e))); return; }
    show($("agents"), false);
    show($("log"), false);
    show($("error"), false);
    if (onDone) onDone(cached.briefing);
    else showCacheBanner(ticker, cached, quarter);
    consumePendingAutoCompare(ticker);
    return;
  }
  hideCacheBanner();
  running = true;
  $("company-go").disabled = true;
  $("compare-search").disabled = true;
  setQuarterButtonsDisabled(true);
  show($("briefing"), false);
  show($("error"), false);
  show($("agents"), true);
  show($("log"), true);
  resetCards();
  logLines = [];
  $("log-list").innerHTML = "";
  $("log-now").textContent = "Now: starting…";
  // Optimistic plan, rendered in the same tick as the click: the
  // full 4-step plan is visible before the first stream event
  // arrives, with an honest time range instead of a point estimate.
  // A resume replays the stored events into the same rail, so its
  // plan line says resuming, not starting.
  if (resumeRunId) {
    setConductor("Resuming run — replaying completed steps", "Finished stages replay instantly · Only the remaining stages run live");
  } else {
    setConductor("Starting — Scout is first", "Step 1 of 4 · Next: Analyst · Usually 30–90s");
  }
  startElapsed();
  try {
    let streamed;
    try {
      streamed = await runStream(ticker, quarter, onDone, resumeRunId);
    } catch (e) {
      streamed = false;
    }
    if (!streamed) {
      setConductor("Now: final briefing only", "Live stream did not speak — no step-by-step view for this run");
      AGENT_ORDER.forEach((a) => {
        setStatus(a, "waiting", "");
        setBody(a, `<p class="agent-waiting">No step-by-step view — the live stream did not speak, so only the final briefing will appear.</p>`);
      });
      try {
        await runPost(ticker, quarter, onDone);
        stopElapsed();
      } catch (e) {
        stopElapsed();
        showBriefingError(ticker, e.message);
      }
    }
  } finally {
    stopElapsed($("conductor-time").textContent || undefined);
    $("company-go").disabled = false;
    $("compare-search").disabled = false;
    setQuarterButtonsDisabled(false);
    running = false;
    // The base run just finished (stream or post path); the
    // running flag is down, so the compare run may start now.
    consumePendingAutoCompare(currentTicker);
  }
}

$("log-download").addEventListener("click", () => {
  if (!logLines.length) return;
  const blob = new Blob([logLines.join("\n") + "\n"], { type: "text/plain" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `briefing-${currentTicker || "BRIEFING"}-log.txt`;
  a.click();
  URL.revokeObjectURL(a.href);
});

// "Resume run" / "Run again" after a lost connection (Batch 31).
// With a run id held, the click resumes that run from its last
// checkpoint; without one (the break hit before run_started),
// it is an explicit fresh run. Only ever shown for connection
// losses, never for a server verdict (FAIL / NOT_REPORTED_YET
// would just repeat).
$("error-retry").addEventListener("click", () => {
  if (running || !currentTicker) return;
  show($("error"), false);
  getBriefing(currentTicker, currentQuarter, null, lastRunId);
});

let lastBriefing = null;
// Shareable comparison links (Batch 14): ?ticker=BASE&compare=SECOND
// runs the base briefing on load, then the compare flow once the
// base finishes. pendingAutoCompare is consumed exactly once, in
// the cache branch or in getBriefing's finally, and only when the
// briefing that just finished is the base — a failed base run
// never triggers a compare against a stale briefing.
let pendingAutoCompare = null;
let lastComparisonLink = "";

// Consume a pending auto-compare after the base run finishes.
// finishedTicker is the ticker whose run just ended (cache or
// stream); the guard ties it to the base the link named.
function consumePendingAutoCompare(finishedTicker) {
  if (!pendingAutoCompare) return;
  const { second, base } = pendingAutoCompare;
  pendingAutoCompare = null;
  if (lastBriefing && lastBriefing.ticker === base && finishedTicker === base) startCompare(second);
}

// Markdown export of the finished briefing: the same record the
// article shows (verdict, claims with derivations, drivers,
// story as written, sources, trace), plus the footer disclaimer
// the page itself carries. Claim lines use the claim text, which
// already carries the rounded figure — never the raw float.
function briefingMarkdown(b) {
  const stripFacts = (d) => roundLongFloats(String(d || "").replace(/, from facts.*$/, ""));
  const lines = [];
  lines.push(`# ${b.ticker} — ${b.quarter_label} earnings briefing`, "");
  lines.push(`**Verdict:** ${b.verdict}`, "");
  lines.push("## Verified claims");
  (b.table || []).forEach((row) => {
    lines.push(`- ${row.claim}`);
    const d = stripFacts(row.derivation);
    if (d) lines.push(`  Derivation: ${d}`);
  });
  lines.push("");
  if ((b.drivers || []).length) {
    lines.push("## What drove the quarter");
    b.drivers.forEach((d) => lines.push(`- ${d}`));
    lines.push("");
  }
  if ((b.kpis || []).length) {
    lines.push("## Company metrics");
    b.kpis.forEach((k) => {
      const v = String(k.value ?? "");
      const shown = (k.unit && /^[\d.,+-]+$/.test(v)) ? v + (k.unit === "%" ? "%" : " " + k.unit) : v;
      lines.push(`- ${k.name || ""} — ${shown}${k.period ? ` (${k.period})` : ""}${k.kind === "outlook" ? " (Outlook)" : ""}`);
    });
    lines.push("From the company's earnings release (exhibit 99.1). Release-extracted, not Critic-verified." + (b.kpi_source_url ? ` Source: ${b.kpi_source_url}` : ""), "");
  }
  if ((b.fine_print || []).length) {
    lines.push("## Fine print — what's new in the filings");
    b.fine_print.forEach((it) => {
      lines.push(`- “${it.quote}” — ${it.why_it_matters} (${it.section})${it.source_url ? ` Source: ${it.source_url}` : ""}`);
    });
    lines.push("LLM-surfaced from this quarter's and last quarter's 10-Q filings and the earnings release. Not Critic-verified; quotes and numbers are verbatim from the filings.", "");
  }
  if (b.diagram && (b.diagram.edges || []).length) {
    lines.push("## How it makes money");
    const names = {};
    (b.diagram.nodes || []).forEach((n) => { names[n.id] = n.label; });
    b.diagram.edges.forEach((e) => {
      lines.push(`- ${names[e.from] || e.from} —${e.kind}→ ${names[e.to] || e.to}${e.label ? ` (${e.label})` : ""}`);
    });
    lines.push("Simplified model — illustrative, from the company's earnings release.", "");
  }
  if (b.market_reaction) {
    lines.push("## Market reaction", b.market_reaction, "");
  }
  if (b.story) {
    lines.push("## Story", b.story, "");
  }
  const isNote = (w) => /No module named|failed:/.test(w);
  const watch = (b.guidance_and_watch || []).filter((w) => !isNote(w));
  const notes = (b.guidance_and_watch || []).filter(isNote);
  if (watch.length) {
    lines.push("## Guidance and what to watch");
    watch.forEach((w) => lines.push(`- ${w}`));
    lines.push("");
  }
  if (notes.length) {
    lines.push("## Data notes");
    notes.forEach((w) => lines.push(`- ${w}`));
    lines.push("");
  }
  lines.push("---", `Story written via: ${b.story_model || "—"}`);
  (b.sources || []).forEach((s) => {
    lines.push(`Source: ${s.publisher || "Source"}${s.url ? ` (${s.url})` : ""}`);
  });
  lines.push(`Trace: ${b.trace_id || "—"}`);
  lines.push(`Exported ${new Date().toLocaleString()} from earningsbrief.pages.dev.`);
  lines.push("Educational demo, not investment advice. No buy, sell, or hold recommendation.");
  return lines.join("\n") + "\n";
}

$("briefing-download").addEventListener("click", () => {
  if (!lastBriefing) return;
  const b = lastBriefing;
  const quarter = String(b.quarter_label || "").replace(/[^A-Za-z0-9]+/g, "-");
  const blob = new Blob([briefingMarkdown(b)], { type: "text/markdown" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `Earnings-Ledger-${b.ticker}-${quarter}.md`;
  a.click();
  URL.revokeObjectURL(a.href);
});

// Quarter picker: the three calendar quarters before the briefing's
// own quarter, derived from its label (never guessed — an
// unparseable label hides the picker). When the briefing is for
// an older quarter, a Latest button leads back. Clicking a button
// runs that quarter through the same pipeline; the cache keeps
// quarters separate, so an older briefing never overwrites the
// latest one.
function prevQuarters(label, count) {
  const m = /^Q([1-4]) (\d{4})$/.exec(label || "");
  if (!m) return [];
  let q = Number(m[1]);
  let y = Number(m[2]);
  const out = [];
  for (let i = 0; i < count; i++) {
    q -= 1;
    if (q === 0) { q = 4; y -= 1; }
    out.push(`Q${q} ${y}`);
  }
  return out;
}

// Batch 20 — fiscal quarters: a fiscal label ("quarter ended
// 2026-07-26") has no computable predecessors — fiscal calendars
// are irregular (52/53-week years, Sunday/Saturday ends) — so its
// previous quarters come from the briefing's own Scout facts:
// real period ends, newest first, excluding the current quarter.
// The buttons show the short label ("Jul 2026") but carry the
// full fiscal label, which the backend now accepts.
function prevFiscalQuarters(label, facts, count) {
  const m = /^quarter ended (\d{4}-\d{2}-\d{2})$/.exec(label || "");
  if (!m) return [];
  const current = m[1];
  const ends = [...new Set((facts || []).map((f) => f.period).filter((p) =>
    /^\d{4}-\d{2}-\d{2}$/.test(p || "")))].filter((p) => p < current).sort().reverse();
  return ends.slice(0, count).map((p) => `quarter ended ${p}`);
}

function renderQuarterPicker(label) {
  const wrap = $("quarter-picker");
  const btns = $("quarter-buttons");
  if (!wrap || !btns) return;
  let prev = prevQuarters(label, 3);
  let fiscal = false;
  if (!prev.length) {
    prev = prevFiscalQuarters(label, lastScoutFacts, 3);
    fiscal = prev.length > 0;
  }
  if (!prev.length) { show(wrap, false); return; }
  let html = prev.map((l) =>
    `<button type="button" class="btn-secondary quarter-btn" data-q="${esc(l)}">${esc(fiscal ? shortQuarterLabel(l) : l)}</button>`).join("");
  if (currentQuarter) {
    html += `<button type="button" class="btn-secondary quarter-btn" data-q="">Latest quarter</button>`;
  }
  btns.innerHTML = html;
  btns.querySelectorAll(".quarter-btn").forEach((btn) => {
    btn.addEventListener("click", () => getBriefing(currentTicker, btn.dataset.q));
  });
  show(wrap, true);
}

// Peer comparison (Batch 8): pure helpers over briefing claim
// lists. Values shown are the backend's own claim values
// (parseClaim's rounded display value) — the frontend computes
// no numbers, it only aligns two briefings' claims by metric.
function claimValueMap(claims) {
  const map = new Map();
  (claims || []).forEach((c) => {
    // Briefing table rows carry `claim`, not `text` (the Analysis
    // claim shape parseClaim was written for). Without this
    // fallback every row parses to a blank metric and the
    // comparison collapses to a single nameless row.
    const p = parseClaim({ ...c, text: c.text ?? c.claim ?? "" });
    // Value plus its direction arrow: parseClaim's value drops the
    // "+" (the Analyst table shows direction via the arrow), but a
    // standalone comparison table needs the direction in the cell.
    if (!map.has(p.metric)) map.set(p.metric, p.value + (p.arrow || ""));
  });
  return map;
}

function alignClaims(baseClaims, secondClaims) {
  const b = claimValueMap(baseClaims);
  const s = claimValueMap(secondClaims);
  return [...new Set([...b.keys(), ...s.keys()])].map((metric) => ({
    metric,
    base: b.has(metric) ? b.get(metric) : "—",
    second: s.has(metric) ? s.get(metric) : "—",
  }));
}

function headlineValue(claims, test) {
  const map = claimValueMap(claims);
  for (const [metric, value] of map) {
    if (test(metric)) return value;
  }
  return "—";
}

function compareTableHtml(baseTicker, secondTicker, rows) {
  const head = `<tr><th>Metric</th><th class="num">${esc(baseTicker)}</th><th class="num">${esc(secondTicker)}</th></tr>`;
  const body = rows.map((r) =>
    `<tr><td>${esc(r.metric)}</td><td class="num">${esc(r.base)}</td><td class="num">${esc(r.second)}</td></tr>`).join("");
  return `<table class="compare-table"><thead>${head}</thead><tbody>${body}</tbody></table>`;
}

function renderComparison(base, second) {
  const sec = $("comparison");
  if (!sec || !base || !second) return;
  // Feature 7: the tab names the pair it shows.
  document.title = `${base.ticker} vs ${second.ticker} | Earnings Ledger`;
  const sameQuarter = base.quarter_label === second.quarter_label;
  $("comparison-title").textContent = `Head to head: ${base.ticker} vs ${second.ticker}`;
  $("comparison-quarters").textContent = sameQuarter
    ? `Both briefings are for ${base.quarter_label}. Figures are each briefing's verified claims.`
    : `Warning: quarters differ (${base.quarter_label} vs ${second.quarter_label}) — figures are not like-for-like.`;
  $("comparison-verdicts").innerHTML =
    `<div class="compare-verdict"><div class="compare-verdict-head">${logoImg(base.ticker, "logo-img logo-verdict")}<span class="badge badge-primary">${esc(base.ticker)}</span></div><p class="body-text">${esc(base.verdict)}</p></div>`
    + `<div class="compare-verdict"><div class="compare-verdict-head">${logoImg(second.ticker, "logo-img logo-verdict")}<span class="badge badge-primary">${esc(second.ticker)}</span></div><p class="body-text">${esc(second.verdict)}</p></div>`;
  const headlineRows = [
    { metric: "Revenue YoY growth",
      base: headlineValue(base.table, (m) => m === "Revenue YoY growth"),
      second: headlineValue(second.table, (m) => m === "Revenue YoY growth") },
    { metric: "Operating margin",
      base: headlineValue(base.table, (m) => m === "Operating margin"),
      second: headlineValue(second.table, (m) => m === "Operating margin") },
    { metric: "EPS vs consensus",
      base: headlineValue(base.table, (m) => m.includes("vs consensus")),
      second: headlineValue(second.table, (m) => m.includes("vs consensus")) },
  ];
  $("comparison-headline").innerHTML = compareTableHtml(base.ticker, second.ticker, headlineRows);
  $("comparison-table").innerHTML = compareTableHtml(
    base.ticker, second.ticker, alignClaims(base.table, second.table));
  const ub = $("comparison-units");
  if (ub) { ub.innerHTML = ""; show(ub, false); }
  show(sec, true);
  renderUnitEconomics(base.ticker, second.ticker);
}

function startCompare(secondTicker) {
  const base = lastBriefing;
  if (!base) return;
  const second = String(secondTicker || "").trim().toUpperCase();
  const note = $("compare-note");
  if (!second) return;
  if (second === base.ticker) {
    if (note) {
      note.textContent = "That's the company already shown — pick a different one.";
      show(note, true);
    }
    return;
  }
  if (note) show(note, false);
  const box = $("compare-results");
  if (box) show(box, false);
  // Latest vs latest, NOT the base's quarter: calendar quarter
  // labels only fit December year-end companies. Forcing the
  // base's label onto a January year-end company (Nvidia's
  // quarters end Jan/Apr/Jul/Oct) invents a quarter it never
  // reported and fails NOT_REPORTED_YET. The comparison names
  // both quarters and warns when they differ.
  const baseQuarter = currentQuarter;
  getBriefing(second, "", (b) => {
    renderComparison(base, b);
    // The shareable comparison link: after the second run rewrote
    // the URL to its own ticker, restore the pair the page shows.
    lastComparisonLink = `${location.origin}${location.pathname}?ticker=${base.ticker}&compare=${second}`
      + (baseQuarter ? `&quarter=${encodeURIComponent(baseQuarter)}` : "");
    try {
      const url = new URL(location.href);
      url.searchParams.set("ticker", base.ticker);
      url.searchParams.set("compare", second);
      if (baseQuarter) url.searchParams.set("quarter", baseQuarter);
      else url.searchParams.delete("quarter");
      history.replaceState(null, "", url);
    } catch { /* URL sharing is best-effort */ }
  });
}

function renderCompareResults(matches) {
  const box = $("compare-results");
  if (!matches.length) {
    box.innerHTML = `<p class="search-empty">No company matched — try a different spelling, or a ticker like NVDA.</p>`;
  } else {
    box.innerHTML = matches.map((m) =>
      `<button type="button" class="chip search-match" data-ticker="${esc(m.ticker)}">`
      + `${logoImg(m.ticker, "logo-img logo-chip")}${esc(m.name)} (${esc(m.ticker)})</button>`).join("");
    box.querySelectorAll(".search-match").forEach((btn) => {
      btn.addEventListener("click", () => {
        show(box, false);
        $("compare-search").value = "";
        startCompare(btn.dataset.ticker);
      });
    });
  }
  show(box, true);
}

// EPS beat/miss badge (Batch 19): the same consensus claim and
// the same "reported vs forecast" parse as the EPS chart, so the
// badge can never disagree with the chart. Hidden when no
// consensus claim exists; the title carries the two numbers.
function renderBeatMissBadge() {
  const el = $("b-beatmiss");
  if (!el) return;
  const parsed = (lastAnalystClaims || []).map(parseClaim);
  const eps = parsed.find((p) => /consensus/i.test(p.metric));
  const m = eps && eps.detail ? eps.detail.match(/\$?([\d.]+)\s*vs\s*\$?([\d.]+)/) : null;
  if (!m) { show(el, false); return; }
  const reported = Number(m[1]), forecast = Number(m[2]);
  let text, cls;
  if (reported > forecast) { text = "▲ EPS beat"; cls = "badge-beat"; }
  else if (reported < forecast) { text = "▼ EPS miss"; cls = "badge-miss"; }
  else { text = "EPS met"; cls = "badge-outline"; }
  el.textContent = text;
  el.className = `badge ${cls}`;
  el.title = `Reported ${m[1]} vs consensus ${m[2]}`;
  show(el, true);
}

// Checked-in line (Batch 19): shown only by a run's completion
// site, with that run's total seconds. render() hides it, so a
// cached briefing never claims a fresh check.
function setCheckedLine(totalSeconds) {
  const el = $("b-checked");
  if (!el) return;
  el.textContent = `Checked in ${totalSeconds}s by Scout, Analyst, Critic, Writer.`;
  show(el, true);
}

// Takeaways (Batch 29): a pure selection from the briefing's own
// verified claims and drivers — the biggest YoY growth move, the
// operating margin, EPS vs consensus, and the top driver, in that
// order, skipping whatever is absent. Claim texts are reused
// verbatim (they are already complete sentences with their
// periods and values); nothing is reworded, so no new number can
// enter through this box. YoY only for the growth pick: QoQ is
// the same metric measured twice and would double-count it.
function takeawaysFor(b) {
  const rows = (b.table || []).map((r) => ({
    text: String(r.claim ?? r.text ?? ""), value: r.value,
  }));
  const out = [];
  const push = (t) => { if (t && !out.includes(t)) out.push(t); };
  const yoy = rows.filter((r) => /YoY growth/.test(r.text) && Number.isFinite(r.value));
  if (yoy.length) {
    yoy.sort((a, b2) => Math.abs(b2.value) - Math.abs(a.value));
    push(yoy[0].text);
  }
  const margin = rows.find((r) => /^Operating margin/.test(r.text));
  if (margin) push(margin.text);
  const eps = rows.find((r) => /^EPS vs consensus/.test(r.text));
  if (eps) push(eps.text);
  const drivers = b.drivers || [];
  if (drivers.length) push(String(drivers[0]));
  return out.slice(0, 4);
}

// Company metrics (Batch 22): release-extracted KPIs, rendered
// from the briefing object. The unit appends only to a bare
// numeric value ("48" + "shops"); a value that already carries
// its unit ("5.4%", "$549.8 million") is shown as-is, so the
// line never reads "5.4% %". The section note always states the
// provenance: release-extracted, never Critic-verified.
function renderKpis(kpis, sourceUrl) {
  const items = Array.isArray(kpis) ? kpis : [];
  show($("sec-kpis"), items.length > 0);
  setHTML($("b-kpis"), items.map((k) => {
    const v = String(k.value ?? "");
    let shown = v;
    if (k.unit && /^[\d.,+-]+$/.test(v)) shown = v + (k.unit === "%" ? "%" : " " + k.unit);
    const label = `${esc(k.name || "")} — ${esc(shown)}${k.period ? " (" + esc(k.period) + ")" : ""}${k.kind === "outlook" ? " (Outlook)" : ""}`;
    return `<li>${label}</li>`;
  }).join(""));
  const note = $("b-kpis-note");
  if (note) {
    note.innerHTML = sourceUrl
      ? `From the company's earnings release (<a href="${esc(sourceUrl)}" target="_blank" rel="noopener">exhibit 99.1</a>). Release-extracted, not Critic-verified.`
      : "From the company's earnings release (exhibit 99.1). Release-extracted, not Critic-verified.";
  }
}

// Fine print (Batch 30): LLM-surfaced new/changed filing
// passages. The section renders only when the briefing carries
// items; each item links its own source filing.
function renderFinePrint(items) {
  const sec = $("sec-fineprint");
  if (!sec) return;
  show(sec, !!(items && items.length));
  setHTML($("b-fineprint"), (items || []).map((it) => {
    const src = it.source_url ? ` <a href="${esc(it.source_url)}" target="_blank" rel="noopener">Source</a>` : "";
    return `<li>“${esc(it.quote)}” — ${esc(it.why_it_matters)} <span class="meta">(${esc(it.section)})${src}</span></li>`;
  }).join(""));
}

// Business-model diagram (Batch 23): a deterministic SVG from a
// validated spec — no AI images, no generated prose. Layout is
// fixed by role: payers and partners share the left column
// (supply side, partners below payers), the company sits center,
// users sit right. Money edges are solid green, value edges
// dashed zinc; return edges (right-to-left, e.g. attention
// flowing back) bow underneath, same-column edges bow left so
// they never cross a node label. Colors come from CSS variables
// so the diagram follows light/dark mode with no re-render.
// The spec's icon field is ignored: the role fixes the glyph.
function diagramSvg(spec) {
  if (!spec || !Array.isArray(spec.nodes) || !spec.nodes.length) return "";
  const COL = { payer: 110, partner: 110, company: 300, user: 490 };
  const ICONS = {
    payer: '<circle r="7"/><path d="M0 -7 V7"/>',
    user: '<circle cy="-4" r="3.5"/><path d="M-7 7 A7 5 0 0 1 7 7"/>',
    company: '<path d="M-7 8 V-8 H7 V8 M-7 0 H7"/>',
    partner: '<circle cx="-3.5" r="4.5"/><circle cx="3.5" r="4.5"/>',
  };
  const byCol = {};
  spec.nodes.forEach((n) => { (byCol[n.role] = byCol[n.role] || []).push(n); });
  // Partners stack below payers in the shared left column.
  const left = [...(byCol.payer || []), ...(byCol.partner || [])];
  const cols = { left, center: byCol.company || [], right: byCol.user || [] };
  const maxN = Math.max(left.length, cols.center.length, cols.right.length, 1);
  const H = 100 * maxN + 30;
  const pos = {};
  const place = (list, x) => list.forEach((n, i) => { pos[n.id] = { x, y: 60 + i * 100 }; });
  place(left, COL.payer);
  place(cols.center, COL.company);
  place(cols.right, COL.user);
  const nodeSvg = spec.nodes.map((n) => {
    const p = pos[n.id];
    if (!p) return "";
    return `<g transform="translate(${p.x},${p.y})"><circle r="17" fill="var(--card)" stroke="var(--border)" stroke-width="1.5"/><g fill="none" stroke="var(--foreground)" stroke-width="1.8" stroke-linecap="round">${ICONS[n.role] || ""}</g><text y="34" text-anchor="middle" font-size="12.5" fill="var(--foreground)">${esc(n.label)}</text></g>`;
  }).join("");
  const edgeSvg = (spec.edges || []).map((e) => {
    const a = pos[e.from], b = pos[e.to];
    if (!a || !b) return "";
    const money = e.kind === "money";
    const color = money ? "var(--green)" : "var(--muted-foreground)";
    const marker = money ? "url(#arr-money)" : "url(#arr-value)";
    const dash = money ? "" : ' stroke-dasharray="6 5"';
    let d, lx, ly;
    if (a.x === b.x) {
      // Same column: bow left, clear of the labels below nodes.
      d = `M ${a.x - 17} ${a.y} Q ${a.x - 70} ${(a.y + b.y) / 2} ${b.x - 17} ${b.y}`;
      lx = a.x - 52; ly = (a.y + b.y) / 2;
    } else {
      const dx = b.x - a.x, dy = b.y - a.y;
      const len = Math.hypot(dx, dy) || 1;
      const sx = a.x + (dx / len) * 24, sy = a.y + (dy / len) * 24;
      const ex = b.x - (dx / len) * 24, ey = b.y - (dy / len) * 24;
      const bow = dx > 0 ? -26 : 64;
      const cx = (sx + ex) / 2, cy = (sy + ey) / 2 + bow;
      d = `M ${sx} ${sy} Q ${cx} ${cy} ${ex} ${ey}`;
      lx = 0.25 * sx + 0.5 * cx + 0.25 * ex;
      ly = 0.25 * sy + 0.5 * cy + 0.25 * ey;
    }
    const label = e.label ? `<text x="${lx}" y="${ly}" text-anchor="middle" font-size="11" fill="var(--muted-foreground)" paint-order="stroke" stroke="var(--card)" stroke-width="4" stroke-linejoin="round">${esc(e.label)}</text>` : "";
    return `<path d="${d}" fill="none" stroke="${color}" stroke-width="2" marker-end="${marker}"${dash}/>${label}`;
  }).join("");
  return `<svg viewBox="0 0 600 ${H}" width="100%" role="img" aria-label="Simplified business model diagram"><defs><marker id="arr-money" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto-start-reverse"><path d="M0 0 L7 3 L0 6 Z" style="fill:var(--green)"/></marker><marker id="arr-value" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto-start-reverse"><path d="M0 0 L7 3 L0 6 Z" style="fill:var(--muted-foreground)"/></marker></defs>${edgeSvg}${nodeSvg}</svg>`;
}

// Who's trading it (Batch 24): company-level activity, fetched
// after the briefing renders — never through the Critic, never
// interpreted. Nasdaq (no CORS headers) comes Worker-side via
// the Orchestrator's /ownership route; Veridion (CORS *) comes
// straight from the browser, so it counts against the visitor's
// own IP on the free 60/hour tier. Each card hides on failure.
// Results memoize per ticker per page load: ownership is
// company-level, so a quarter change or cache restore reuses it.
const VERIDION_URL = "https://www.veridionmarkets.com/api/v1/disclosures";
const ownershipCache = {};

function veridionRows(data, ticker) {
  const rows = [];
  for (const r of (data && data.data) || []) {
    if (!r || !r.member || !r.asset) continue;
    if (String(r.asset.ticker || "").toUpperCase() !== ticker) continue;
    const amount = r.amount || {};
    const range = amount.verbatim_text
      || ((amount.range_low != null && amount.range_high != null)
        ? `$${Number(amount.range_low).toLocaleString()} - $${Number(amount.range_high).toLocaleString()}` : "");
    if (!range) continue;
    // The API also returns a midpoint. It is never read here, so
    // it cannot leak into a card: ranges only, as disclosed.
    rows.push({
      name: r.member.full_name || "", party: r.member.party || "",
      chamber: r.member.chamber || "", state: r.member.state || "",
      type: (r.transaction && r.transaction.type) || "",
      date: (r.transaction && r.transaction.date) || "",
      filed: (r.filing && r.filing.filed_date) || "",
      range,
    });
  }
  return rows;
}

function insiderCardHtml(ins) {
  if (!ins) return "";
  const parts = [];
  if (ins.buys12 || ins.sells12) {
    parts.push(`<p class="body-text">Open market buys: ${esc(ins.buys3 || "—")} in 3 months, ${esc(ins.buys12 || "—")} in 12 months. Sells: ${esc(ins.sells3 || "—")} in 3 months, ${esc(ins.sells12 || "—")} in 12 months.</p>`);
  }
  if (ins.net3 || ins.net12) {
    parts.push(`<p class="body-text">Net share activity: ${esc(ins.net3 || "—")} in 3 months, ${esc(ins.net12 || "—")} in 12 months.</p>`);
  }
  if ((ins.recent || []).length) {
    parts.push("<ul class=\"list\">" + ins.recent.map((t) => `<li>${esc(t.insider)} (${esc(t.relation)}) — ${esc(t.type)}, ${esc(t.shares)} shares @ ${esc(t.price)} on ${esc(t.date)}, holds ${esc(t.held)}</li>`).join("") + "</ul>");
    if (ins.total_records) parts.push(`<p class="meta">${esc(String(ins.total_records))} insider transactions in the Nasdaq table.</p>`);
  }
  return parts.join("");
}

function fundsCardHtml(f) {
  if (!f) return "";
  const parts = [];
  if (f.ownership_pct) {
    parts.push(`<p class="body-text">Institutional ownership: ${esc(f.ownership_pct)} of ${esc(f.shares_outstanding || "—")} million shares outstanding.</p>`);
  }
  const pos = [...(f.positions || []), ...(f.new_sold_out || [])];
  if (pos.length) {
    parts.push("<ul class=\"list\">" + pos.map((p) => `<li>${esc(p.label)} — ${esc(p.holders)} holders, ${esc(p.shares)} shares</li>`).join("") + "</ul>");
  }
  if ((f.top || []).length) {
    parts.push("<p class=\"body-text\">Largest holders as listed:</p><ul class=\"list\">" + f.top.map((h) => `<li>${esc(h.owner)} — ${esc(h.shares)} shares (${esc(h.change_pct || "—")}%) as of ${esc(h.date)}</li>`).join("") + "</ul>");
  }
  return parts.join("");
}

function politiciansCardHtml(rows) {
  if (!rows || !rows.length) return "";
  const items = rows.slice(0, 10).map((r) => {
    const who = `${r.name} (${r.party}${r.chamber ? `, ${r.chamber}` : ""}${r.state ? ` ${r.state}` : ""})`;
    const type = r.type ? r.type.charAt(0).toUpperCase() + r.type.slice(1) : "";
    return `<li>${esc(who)} — ${esc(type)} ${esc(r.range)}${r.date ? `, traded ${esc(r.date)}` : ""}${r.filed ? `, filed ${esc(r.filed)}` : ""}</li>`;
  }).join("");
  const more = rows.length > 10 ? `<p class="meta">Showing the 10 most recent of ${rows.length} returned.</p>` : "";
  return `<ul class="list">${items}</ul>${more}`;
}

async function renderOwnership(ticker) {
  const sec = $("ownership");
  if (!sec || !ticker) return;
  const apply = (data) => {
    setText($("ownership-title"), `Who's trading ${ticker}`);
    const ins = insiderCardHtml(data.insiders);
    const fun = fundsCardHtml(data.funds);
    const pol = politiciansCardHtml(data.politicians);
    show($("own-insiders-card"), !!ins);
    setHTML($("own-insiders"), ins);
    show($("own-funds-card"), !!fun);
    setHTML($("own-funds"), fun);
    show($("own-politicians-card"), !!pol);
    setHTML($("own-politicians"), pol);
    show(sec, !!(ins || fun || pol));
  };
  if (ownershipCache[ticker]) { apply(ownershipCache[ticker]); return; }
  try {
    const [nas, ver] = await Promise.allSettled([
      fetch(`${ORCHESTRATOR_URL}/ownership?ticker=${encodeURIComponent(ticker)}`).then((r) => (r.ok ? r.json() : null)),
      fetch(`${VERIDION_URL}?ticker=${encodeURIComponent(ticker)}&limit=25`, { headers: { Accept: "application/json" } }).then((r) => (r.ok ? r.json() : null)),
    ]);
    const data = {
      insiders: nas.status === "fulfilled" && nas.value ? nas.value.insiders : null,
      funds: nas.status === "fulfilled" && nas.value ? nas.value.funds : null,
      politicians: ver.status === "fulfilled" && ver.value ? veridionRows(ver.value, ticker) : [],
    };
    ownershipCache[ticker] = data;
    apply(data);
  } catch { show(sec, false); }
}

// Fiscal.ai-style visuals (Batch 26): long-history charts from
// the Orchestrator's /history route — computed server-side, never
// LLM-written. The vs-chart and long bars follow the trend
// switcher's metric; results memoize per ticker+metric.
const HISTORY_LABELS = { total_revenue: "Revenue", operating_income: "Operating income",
  net_income: "Net income", ebitda: "EBITDA", operating_cash_flow: "Operating cash flow",
  free_cash_flow: "Free cash flow", buybacks: "Buybacks", shares_outstanding: "Shares outstanding" };
const historyCache = {};

function fmtPct(v) {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
}
function fmtMoney(v) {
  if (v == null || !Number.isFinite(v)) return "—";
  const abs = Math.abs(v);
  if (abs >= 1e12) return `$${(v / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
  return `$${Math.round(v).toLocaleString()}`;
}
function cagrFromPct(totalPct, firstDate, lastDate) {
  if (totalPct == null || !firstDate || !lastDate) return null;
  const days = (new Date(lastDate) - new Date(firstDate)) / 86400000;
  if (!(days > 0)) return null;
  return (Math.pow(1 + totalPct / 100, 365.25 / days) - 1) * 100;
}
function isoShort(iso) {
  const m = String(iso || "").match(/^(\d{4})-(\d{2})-\d{2}$/);
  if (!m) return String(iso || "");
  return `${["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][Number(m[2]) - 1]} ${m[1]}`;
}
function vsChartData(payload, metricLabel) {
  const tr = payload && payload.total_return;
  if (!tr || !tr.points || tr.points.length < 2 || !tr.metric_points || tr.metric_points.length < 2) return null;
  const ends = tr.points.map((p) => p.period_end);
  const labels = ends.map((e) => {
    const p = (payload.series || []).find((s) => s.period_end === e);
    return (p && p.label) || isoShort(e);
  });
  const metricTotal = tr.metric_points[tr.metric_points.length - 1].value_pct;
  const metricCagr = cagrFromPct(metricTotal, ends[0], ends[ends.length - 1]);
  return { labels,
    datasets: [
      { label: `Total return ${fmtPct(tr.total_change_pct)} (CAGR ${fmtPct(tr.cagr_pct)})`,
        data: tr.points.map((p) => p.value_pct) },
      { label: `${metricLabel} ${fmtPct(metricTotal)} (CAGR ${fmtPct(metricCagr)})`,
        data: tr.metric_points.map((p) => p.value_pct) },
    ] };
}
function longChartData(payload) {
  const series = (payload && payload.series) || [];
  if (series.length < 2) return null;
  return { labels: series.map((p) => p.label || isoShort(p.period_end)),
    data: series.map((p) => p.value) };
}
function readLineText(rl) {
  if (!rl) return "";
  const parts = [`Peak ${fmtMoney(rl.peak_value)} in ${isoShort(rl.peak_end)}`];
  if (rl.current_vs_peak_pct != null) parts.push(`now ${fmtPct(rl.current_vs_peak_pct)} vs peak`);
  parts.push(`longest rise ${rl.longest_rise_quarters} quarters, longest decline ${rl.longest_decline_quarters} quarters`);
  if (rl.biggest_jump) {
    parts.push(`biggest quarterly move ${fmtPct(rl.biggest_jump.pct)} (${isoShort(rl.biggest_jump.from_end)} → ${isoShort(rl.biggest_jump.to_end)})`);
  }
  return parts.join("; ") + ".";
}

async function renderHistory(ticker) {
  if (!ticker || !lastBriefing || lastBriefing.ticker !== ticker) return;
  const metric = trendMetric;
  const key = `${ticker}:${metric}`;
  const label = HISTORY_LABELS[metric] || "Revenue";
  const vsTitle = $("chart-vs-metric");
  if (vsTitle) vsTitle.textContent = label.toLowerCase();
  const longTitle = $("chart-long-metric");
  if (longTitle) longTitle.textContent = label.toLowerCase();
  const apply = (payload) => {
    if (!lastBriefing || lastBriefing.ticker !== ticker) return; // stale
    const vs = vsChartData(payload, label);
    if (vs) {
      setChartEmpty("vs", false);
      makeChart("vs", "line", vs.labels, [
        { label: vs.datasets[0].label, data: vs.datasets[0].data,
          borderColor: themeColor("#1d4ed8", "#60a5fa"), backgroundColor: "transparent", tension: 0.2, pointRadius: 0 },
        { label: vs.datasets[1].label, data: vs.datasets[1].data,
          borderColor: themeColor("#0f766e", "#2dd4bf"), backgroundColor: "transparent", tension: 0.2, pointRadius: 0 },
      ]);
    } else { destroyChart("vs"); setChartEmpty("vs", true); }
    const lng = longChartData(payload);
    if (lng) {
      setChartEmpty("long", false);
      makeChart("long", "bar", lng.labels, [{ label, data: lng.data,
        backgroundColor: lng.labels.map((_, i) => i === lng.labels.length - 1 ? themeColor("#1d4ed8", "#60a5fa") : "#93c5fd"),
        borderRadius: 6 }]);
      const rl = $("chart-long-read");
      if (rl) { const text = readLineText(payload.read_line); rl.textContent = text; show(rl, !!text); }
    } else {
      destroyChart("long"); setChartEmpty("long", true);
      const rl = $("chart-long-read");
      if (rl) show(rl, false);
    }
    setChartsVisible();
  };
  if (historyCache[key]) { apply(historyCache[key]); return; }
  try {
    const resp = await fetch(`${ORCHESTRATOR_URL}/history?ticker=${encodeURIComponent(ticker)}&metric=${encodeURIComponent(metric)}`);
    if (!resp.ok) throw new Error(`history ${resp.status}`);
    const payload = await resp.json();
    historyCache[key] = payload;
    apply(payload);
  } catch {
    destroyChart("vs"); destroyChart("long");
    setChartEmpty("vs", true); setChartEmpty("long", true);
  }
}

async function renderUnitEconomics(baseTicker, secondTicker) {
  const box = $("comparison-units");
  if (!box) return;
  const fetchHist = async (t, m) => {
    try {
      const r = await fetch(`${ORCHESTRATOR_URL}/history?ticker=${encodeURIComponent(t)}&metric=${encodeURIComponent(m)}`);
      return r.ok ? r.json() : null;
    } catch { return null; }
  };
  const [revB, hcB, revS, hcS] = await Promise.all([
    fetchHist(baseTicker, "total_revenue"), fetchHist(baseTicker, "headcount"),
    fetchHist(secondTicker, "total_revenue"), fetchHist(secondTicker, "headcount"),
  ]);
  const perEmployee = (rev, hc) => {
    const r = rev && rev.series && rev.series.length ? rev.series[rev.series.length - 1] : null;
    const h = hc && hc.series && hc.series.length ? hc.series[hc.series.length - 1] : null;
    if (!r || !h || !h.value) return null;
    return { value: r.value / h.value, revLabel: r.label, revValue: r.value,
      hcLabel: h.label, hcValue: h.value };
  };
  const b = perEmployee(revB, hcB), s = perEmployee(revS, hcS);
  if (!b || !s) { show(box, false); box.innerHTML = ""; return; }
  box.innerHTML = `<h4>Per unit</h4><p class="body-text">${esc(baseTicker)}: ${fmtMoney(b.value)} revenue per employee — ${fmtMoney(b.revValue)} revenue (${esc(b.revLabel)}) ÷ ${esc(Number(b.hcValue).toLocaleString())} employees (${esc(b.hcLabel)}).<br>`
    + `${esc(secondTicker)}: ${fmtMoney(s.value)} revenue per employee — ${fmtMoney(s.revValue)} revenue (${esc(s.revLabel)}) ÷ ${esc(Number(s.hcValue).toLocaleString())} employees (${esc(s.hcLabel)}).</p>`
    + `<p class="meta">Revenue is the latest quarterly XBRL figure; headcount is the latest DEI-tagged 10-K figure. The row hides when either input is missing for either company.</p>`;
  show(box, true);
}

function render(b) {
  lastBriefing = b;
  renderFacts = lastScoutFacts;
  renderQuarterPicker(b.quarter_label);
  // Feature 7: the tab names the company and quarter it shows.
  document.title = `${b.ticker} — ${b.quarter_label} | Earnings Ledger`;
  setText($("b-ticker"), b.ticker);
  setHTML($("b-logo"), logoImg(b.ticker, "logo-img logo-header"));
  setText($("b-quarter"), b.quarter_label);
  // Feature 2: the verdict's first glossary term per render gets
  // a dotted underline + button (same shared popover as claims).
  setHTML($("b-verdict"), glossifyHtml(esc(b.verdict), new Set()));
  wireGlossButtons($("b-verdict"));
  // Feature 3: the find box rides with the article; a new render
  // resets its state (a stale query would count the old briefing).
  show($("briefing-find"), true);
  resetFind();
  // Takeaways (Batch 29): derived only from this briefing's own
  // verified claims and drivers — no new model call, no new cost.
  // Unlike the checked line, these need no fresh run: a cache
  // restore recomputes the same bullets from the stored briefing.
  const takeaways = takeawaysFor(b);
  show($("sec-takeaways"), takeaways.length > 0);
  setHTML($("b-takeaways"), takeaways.map((t) => `<li>${esc(t)}</li>`).join(""));
  // Claim values are percentages; the raw float (8.868501529051978)
  // is an internal artifact, so round to the one decimal the claim
  // text itself uses. The RAW derivation is kept here (with its
  // "from facts …" suffix): parseClaim strips that suffix for
  // display, and the popover matches sources against it — so the
  // display never shows internal fact IDs, but the trace survives.
  // Same claim blocks as the Analyst card, so the record matches
  // what the card showed.
  const briefingClaims = (b.table || []).map((row) => ({
    text: row.claim, value: row.value,
    derivation: String(row.derivation || ""),
  }));
  lastAnalystClaims = briefingClaims;
  renderAnalyst("briefing", briefingClaims, $("b-table"), "", lastScoutFacts, { ticker: b.ticker, quarter: b.quarter_label });
  updateAllCharts(b.quarter_label);
  renderBeatMissBadge();
  // The checked line belongs to a fresh run only: render() also
  // serves cache restores, where no check happened this visit,
  // so it starts hidden here and the run's completion site
  // shows it with that run's time (Batch 19).
  show($("b-checked"), false);
  const drivers = b.drivers || [];
  show($("sec-drivers"), drivers.length > 0);
  setHTML($("b-drivers"), drivers.map((d) => `<li>${esc(d)}</li>`).join(""));
  renderKpis(b.kpis, b.kpi_source_url);
  renderFinePrint(b.fine_print);
  show($("sec-diagram"), !!b.diagram);
  setHTML($("b-diagram"), b.diagram ? diagramSvg(b.diagram) : "");
  renderOwnership(b.ticker);
  renderHistory(b.ticker);
  show($("sec-market"), Boolean(b.market_reaction));
  setText($("b-reaction"), b.market_reaction || "");
  setHTML($("b-story"), storyHtml(b.story || ""));
  setText($("b-model"), b.story_model || "—");
  setHTML($("b-sources"), (b.sources || []).map((s) => {
    const label = esc(s.publisher || "Source");
    return s.url ? `<li><a href="${esc(s.url)}" target="_blank" rel="noopener">${label}</a></li>`
                 : `<li>${label}</li>`;
  }).join(""));
  setText($("b-trace"), b.trace_id || "—");
  // The Analyst copies pack.missing into risks, so tool notes (the
  // absent price feed, in the cloud build) arrive inside
  // guidance_and_watch. They are honest data notes, not guidance,
  // so show them under their own heading instead of hiding them.
  const isNote = (w) => /No module named|failed:/.test(w);
  const watch = (b.guidance_and_watch || []).filter((w) => !isNote(w));
  const notes = (b.guidance_and_watch || []).filter(isNote);
  show($("sec-watch"), watch.length > 0);
  setHTML($("b-watch"), watch.map((w) => `<li>${esc(w)}</li>`).join(""));
  show($("sec-notes"), notes.length > 0);
  setHTML($("b-notes"), notes.map((w) => `<li>${esc(w)}</li>`).join(""));
  show($("briefing"), true);
}



// ---- Company-name search (Cloudflare AI Search) ----
// The namespace public endpoint searches ONLY the "companies"
// instance (allowlisted server-side), rate-limited to 60/min
// and host-locked to this site. Search runs on button/Enter
// only — never per keystroke — and results are cached per
// query for the session, so the free query pool (1,000
// semantic/month) is never burned by typing.
//
// Response shape, confirmed by a live probe Nov 2, 2026
// ("Apple" query): {success, result: {query_kind,
// search_query, chunks: [{text, item: {key: <page URL>},
// score, instance_id, ...}]}}. The ticker comes from the
// chunk's page URL (/companies/<TICKER>) or from "Ticker:
// XXX" in its text; the directory-index chunk matches neither
// and is skipped. Chunks arrive score-ordered; the first
// matches are shown, the user picks. If the shape ever
// changes, this parser is the one place to fix.
const SEARCH_URL = "https://ns-cc6b2129-061a-495e-bfa6-d2a47919f37a.search.ai.cloudflare.com/search";
const LOG_URL = "https://mesh-search-log-proof.tejpreetsingh1988.workers.dev";

// Fire-and-forget: saving a search must never break or slow a search.
// Rows store only the query text, the picked ticker, and a timestamp.
function logSearch(query, ticker) {
  try {
    fetch(LOG_URL + "/log", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, ticker: ticker || null }),
    }).catch(() => {});
  } catch { /* logging never breaks search */ }
}
const searchCache = new Map();
let searching = false;

function itemText(item) {
  if (!item || typeof item !== "object") return "";
  for (const key of ["content", "text", "snippet", "response_text"]) {
    if (typeof item[key] === "string" && item[key]) return item[key];
  }
  return "";
}

function itemSource(item) {
  if (!item || typeof item !== "object") return "";
  if (item.item && typeof item.item.key === "string" && item.item.key) return item.item.key;
  const meta = item.metadata || {};
  for (const key of ["url", "source", "filename", "key", "name"]) {
    if (typeof item[key] === "string" && item[key]) return item[key];
    if (typeof meta[key] === "string" && meta[key]) return meta[key];
  }
  return "";
}

function matchFromItem(item) {
  const text = itemText(item);
  const source = itemSource(item);
  const urlMatch = source.match(/\/companies\/([A-Z]{1,5})\b/);
  const textMatch = text.match(/Ticker:\s*([A-Z]{1,5})\b/);
  const ticker = (urlMatch && urlMatch[1]) || (textMatch && textMatch[1]);
  if (!ticker) return null;
  const heading = text.match(/#\s*([^#\n(]+?)\s*\(\s*[A-Z]{1,5}\s*\)/);
  const name = heading ? heading[1].trim() : ticker;
  return { ticker, name };
}

// Company logos (Batch 10): Parqet's ticker-keyed logo
// endpoint — no key, no domain mapping, crisp SVG for
// every directory ticker tested (AAPL, DDOG, RBLX, KR,
// SO, NEE, MAR, HLT, CMG, DUK all 200). An unknown
// ticker 404s cleanly, so onerror swaps in a muted
// initials tile instead of a broken image — the page
// never shows a missing-logo icon.
function logoUrl(ticker) {
  return `https://assets.parqet.com/logos/symbol/${encodeURIComponent(ticker)}`;
}

function logoImg(ticker, cls) {
  return `<img src="${logoUrl(ticker)}" alt="" class="${cls}" loading="lazy" onerror="logoFallback(this, '${esc(ticker)}')">`;
}

function logoFallback(img, ticker) {
  const span = document.createElement("span");
  span.className = img.className.replace("logo-img", "logo-initials");
  span.textContent = ticker.slice(0, 2);
  img.replaceWith(span);
}

function renderSearchResults(matches, query, fallback = false) {
  const box = $("company-results");
  if (!matches.length) {
    box.innerHTML = fallback
      ? `<p class="search-empty">No company matched "${esc(query)}" in the index or the directory — try a different spelling, `
        + `or a ticker like GOOGL (each company page carries its ticker).</p>`
      : `<p class="search-empty">No company matched "${esc(query)}" — try a different spelling, `
        + `or a ticker like GOOGL (each company page carries its ticker).</p>`;
    // Feature 8: a mistyped name still lands on the right company.
    // Suggestions come from the local directory only (already
    // loaded by the time a search runs) and are NEVER
    // search-logged — clicking one runs the briefing directly.
    const suggestions = didYouMean(query, directoryCache || []);
    if (suggestions.length) {
      box.innerHTML += `<p class="did-you-mean-label">Did you mean:</p>`
        + suggestions.map((m) =>
          `<button type="button" class="chip search-match did-you-mean-chip" data-ticker="${esc(m.ticker)}">`
          + `${logoImg(m.ticker, "logo-img logo-chip")}${esc(m.name)} (${esc(m.ticker)})</button>`).join("");
      box.querySelectorAll(".did-you-mean-chip").forEach((btn) => {
        btn.addEventListener("click", () => {
          show(box, false);
          getBriefing(btn.dataset.ticker);
        });
      });
    }
  } else {
    const note = fallback
      ? `<p class="search-empty">No indexed matches — showing directory matches instead.</p>` : "";
    box.innerHTML = note + matches.map((m) =>
      `<button type="button" class="chip search-match" data-ticker="${esc(m.ticker)}">`
      + `${logoImg(m.ticker, "logo-img logo-chip")}${esc(m.name)} (${esc(m.ticker)})</button>`).join("");
    box.querySelectorAll(".search-match").forEach((btn) => {
      btn.addEventListener("click", () => {
        show(box, false);
        logSearch(query, btn.dataset.ticker);
        getBriefing(btn.dataset.ticker);
      });
    });
  }
  show(box, true);
}

async function searchCompanies() {
  const query = $("company-search").value.trim();
  const box = $("company-results");
  if (!query || searching) return;
  logSearch(query, null);
  if (searchCache.has(query)) {
    const hit = searchCache.get(query);
    renderSearchResults(hit.matches, query, hit.fallback);
    return;
  }
  searching = true;
  box.innerHTML = `<p class="search-empty">Searching…</p>`;
  show(box, true);
  try {
    const resp = await fetch(SEARCH_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: [{ role: "user", content: query }] }),
    });
    if (!resp.ok) throw new Error(`Search failed (HTTP ${resp.status})`);
    const body = await resp.json();
    const result = body.result || {};
    const items = result.chunks || body.data || body.results || body.chunks || [];
    const seen = new Set();
    const matches = [];
    for (const item of items) {
      const m = matchFromItem(item);
      if (m && !seen.has(m.ticker)) {
        seen.add(m.ticker);
        matches.push(m);
        if (matches.length >= 5) break;
      }
    }
    searchCache.set(query, { matches, fallback: false });
    if (!matches.length) {
      // Batch 18: the index found nothing — fall back to the
      // local directory substring filter (the same matcher as
      // the instant suggestions) instead of a dead end. This
      // never burns extra AI Search quota, and the note says so.
      // The fallback result is cached with its flag, so a repeat
      // search replays the same note rather than re-querying.
      const dir = await loadDirectory();
      const q = query.toLowerCase();
      const local = dir.filter((c) =>
        c.name.toLowerCase().includes(q) || c.ticker.toLowerCase().includes(q),
      ).slice(0, 5);
      searchCache.set(query, { matches: local, fallback: true });
      renderSearchResults(local, query, true);
      return;
    }
    renderSearchResults(matches, query);
  } catch (e) {
    box.innerHTML = `<p class="search-empty">Company search is unavailable right now (${esc(e.message)}) — try a different spelling, or pick a company from the instant matches above.</p>`;
    show(box, true);
  } finally {
    searching = false;
  }
}

$("company-go").addEventListener("click", searchCompanies);
$("company-search").addEventListener("keydown", (e) => {
  if (e.key === "Enter") searchCompanies();
});

// Instant local suggestions: filter the company directory in the
// browser as you type — zero AI Search calls, so the free query
// pool is never burned by typing. Full AI search still runs on
// Search click/Enter. Clicking an instant match logs and runs
// its briefing exactly like an AI-search match.
let directoryCache = null;
async function loadDirectory() {
  if (directoryCache) return directoryCache;
  try {
    const resp = await fetch("companies/companies.json");
    directoryCache = await resp.json();
  } catch { directoryCache = []; }
  return directoryCache;
}
$("company-search").addEventListener("input", async (e) => {
  const q = e.target.value.trim().toLowerCase();
  const box = $("company-results");
  if (q.length < 2) { show(box, false); return; }
  if (searching) return;
  const dir = await loadDirectory();
  // Guard against out-of-order resolves while the user keeps typing.
  if ($("company-search").value.trim().toLowerCase() !== q) return;
  const matches = dir.filter((c) =>
    c.name.toLowerCase().includes(q) || c.ticker.toLowerCase().includes(q),
  ).slice(0, 5);
  if (!matches.length) { show(box, false); return; }
  renderSearchResults(matches, e.target.value.trim());
});

// Compare picker: same local directory, instant matches only.
// Deliberately not logged to the search log — a compare pick is
// not a briefing search, and it should not feed "most searched".
$("compare-search").addEventListener("input", async (e) => {
  const q = e.target.value.trim().toLowerCase();
  const box = $("compare-results");
  if (q.length < 2) { show(box, false); return; }
  const dir = await loadDirectory();
  if ($("compare-search").value.trim().toLowerCase() !== q) return;
  const matches = dir.filter((c) =>
    c.name.toLowerCase().includes(q) || c.ticker.toLowerCase().includes(q),
  ).slice(0, 5);
  if (!matches.length) { show(box, false); return; }
  renderCompareResults(matches);
});

// Copy comparison link (Batch 14): the link the compare run
// restored into the URL — the pair the page shows, not the
// second briefing's own ticker. Falls back to a textarea copy
// where the async clipboard API is unavailable.
const shareBtn = $("comparison-share");
if (shareBtn) shareBtn.addEventListener("click", async () => {
  const link = lastComparisonLink || location.href;
  let ok = false;
  try { await navigator.clipboard.writeText(link); ok = true; }
  catch {
    try {
      const ta = document.createElement("textarea");
      ta.value = link; ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select();
      ok = document.execCommand("copy");
      ta.remove();
    } catch { ok = false; }
  }
  if (!ok) return;
  const orig = shareBtn.textContent;
  shareBtn.textContent = "Link copied";
  setTimeout(() => { shareBtn.textContent = orig; }, 2000);
});

// Trend metric switcher (Batch 15): re-renders only the trend
// chart from the facts already held — no new pipeline call.
document.querySelectorAll("[data-trend-metric]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const m = btn.dataset.trendMetric;
    if (!m || m === trendMetric) return;
    trendMetric = m;
    document.querySelectorAll("[data-trend-metric]").forEach((b) =>
      b.classList.toggle("is-active", b === btn));
    if (lastScoutFacts.length) updateTrendChart();
    if (lastBriefing) renderHistory(lastBriefing.ticker);
  });
});

// Recent searches strip: what other visitors searched for, from
// the search log. Clicking a chip runs that search again (which
// itself gets logged, like any search). Stays hidden when the
// log is unreachable.
async function renderRecentSearches() {
  const wrap = $("recent-searches");
  const chips = $("recent-chips");
  if (!wrap || !chips) return;
  try {
    const resp = await fetch(LOG_URL + "/recent?limit=20");
    if (!resp.ok) return;
    const body = await resp.json();
    const seen = new Set();
    const items = (body.searches || []).filter((s) => {
      if (!s.query || seen.has(s.query.toLowerCase())) return false;
      seen.add(s.query.toLowerCase());
      return true;
    }).slice(0, 8);
    if (!items.length) return;
    chips.innerHTML = items.map((s) =>
      `<button type="button" class="chip search-match" data-q="${esc(s.query)}">${esc(s.query)}${s.ticker ? ` (${esc(s.ticker)})` : ""}</button>`).join("");
    chips.querySelectorAll(".search-match").forEach((btn) => {
      btn.addEventListener("click", () => {
        $("company-search").value = btn.dataset.q;
        searchCompanies();
      });
    });
    show(wrap, true);
  } catch { /* strip stays hidden when the log is unreachable */ }
}
renderRecentSearches();

// Most searched strip: top queries by count from the search log.
// Same chip behavior as recent searches; stays hidden when the
// log is unreachable or empty.
async function renderMostSearched() {
  const wrap = $("most-searched");
  const chips = $("most-chips");
  if (!wrap || !chips) return;
  try {
    const resp = await fetch(LOG_URL + "/stats");
    if (!resp.ok) return;
    const body = await resp.json();
    const top = (body.top || []).filter((t) => t.query && t.count > 0).slice(0, 8);
    if (!top.length) return;
    chips.innerHTML = top.map((t) =>
      `<button type="button" class="chip search-match" data-q="${esc(t.query)}">${esc(t.query)} ×${t.count}</button>`).join("");
    chips.querySelectorAll(".search-match").forEach((btn) => {
      btn.addEventListener("click", () => {
        $("company-search").value = btn.dataset.q;
        searchCompanies();
      });
    });
    show(wrap, true);
  } catch { /* strip stays hidden when the log is unreachable */ }
}
renderMostSearched();

// Recent briefings strip: the briefings already saved in this
// browser's cache, newest first. Clicking one restores it instantly
// through the normal cache path (banner + Refresh included) — it
// never re-runs the pipeline and never writes a search-log row.
// Stored only on this device, in localStorage; Clear wipes the keys.
function listCachedBriefings() {
  const items = [];
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (!key || !key.startsWith("ame_briefing_")) continue;
      try {
        const entry = JSON.parse(localStorage.getItem(key));
        if (!entry || !entry.briefing || !entry.savedAt) continue;
        const rest = key.slice("ame_briefing_".length);
        const cut = rest.lastIndexOf("_");
        const ticker = entry.briefing.ticker || (cut > 0 ? rest.slice(0, cut) : rest);
        const q = cut > 0 ? rest.slice(cut + 1) : "";
        items.push({ ticker, quarter: q === "LATEST" ? "" : q, label: entry.briefing.quarter_label || "", savedAt: entry.savedAt });
      } catch { /* skip corrupt entries */ }
    }
  } catch { return []; }
  items.sort((a, b) => b.savedAt - a.savedAt);
  return dedupeBriefingItems(items).slice(0, 8);
}
// [PHASE1-PURE:dedupeBriefingItems]
// One chip per (ticker, quarter label): the same briefing can sit under
// several cache keys (legacy ame_briefing_<T>, LATEST, explicit quarter),
// and each key used to render its own identical chip — NVDA · Jul 2026
// showed four times live (Nov 5, 2026). Keep the newest save per label.
function dedupeBriefingItems(items) {
  const seen = new Set();
  return items.filter((it) => {
    const k = `${it.ticker}|${it.label}`;
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
}
// [/PHASE1-PURE]
// Short chip label for a quarter: "quarter ended 2026-08-30" is
// too long for a chip, so it reads "Aug 2026". Calendar labels
// ("Q3 2026") pass through unchanged. Display only — the briefing
// itself keeps the full label.
const SHORT_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function shortQuarterLabel(label) {
  const m = /^quarter ended (\d{4})-(\d{2})-\d{2}$/.exec(String(label || ""));
  if (!m) return label || "";
  return `${SHORT_MONTHS[Number(m[2]) - 1]} ${m[1]}`;
}
function renderRecentBriefings() {
  const wrap = $("recent-briefings");
  const chips = $("recent-briefing-chips");
  if (!wrap || !chips) return;
  const items = listCachedBriefings();
  if (!items.length) {
    // Clear stale chips too: with display:flex the hidden attribute
    // alone would not hide this strip (see the CSS note), so an
    // empty strip must not leave old chips behind either.
    chips.innerHTML = "";
    show(wrap, false);
    return;
  }
  chips.innerHTML = items.map((it) =>
    `<button type="button" class="chip" data-t="${esc(it.ticker)}" data-q="${esc(it.quarter)}">${esc(it.ticker)}${it.label ? ` · ${esc(shortQuarterLabel(it.label))}` : ""}</button>`).join("");
  chips.querySelectorAll(".chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (running) return;
      getBriefing(btn.dataset.t, btn.dataset.q);
    });
  });
  show(wrap, true);
}
$("recent-briefings-clear").addEventListener("click", () => {
  try {
    const keys = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.startsWith("ame_briefing_")) keys.push(k);
    }
    keys.forEach((k) => localStorage.removeItem(k));
  } catch { /* cache is best-effort */ }
  renderRecentBriefings();
});
renderRecentBriefings();

// Dark mode (Batch 16): the head script already set data-theme
// before first paint; this syncs the button label, the Chart.js
// defaults, and any charts already drawn. Stored choice wins on
// the next visit; otherwise the OS setting applies (head script).
function currentTheme() {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}
function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  try { localStorage.setItem("ame_theme", theme); } catch {}
  const toggle = $("theme-toggle");
  if (toggle) toggle.textContent = theme === "dark" ? "Light mode" : "Dark mode";
  if (typeof Chart !== "undefined") {
    Chart.defaults.color = theme === "dark" ? "#a1a1aa" : "#71717a";
    Chart.defaults.borderColor = theme === "dark" ? "#27272a" : "#e4e4e7";
  }
  if (lastScoutFacts.length || lastAnalystClaims.length) updateAllCharts();
}
const themeToggle = $("theme-toggle");
if (themeToggle) themeToggle.addEventListener("click", () =>
  applyTheme(currentTheme() === "dark" ? "light" : "dark"));
applyTheme(currentTheme());

// Shareable briefing links: ?ticker=INTC runs that briefing on load,
// with ?quarter=Q2%202026 when the link names an older quarter.
// ?ticker=BASE&compare=SECOND additionally runs the compare flow
// once the base briefing finishes (Batch 14).
try {
  const params = new URLSearchParams(location.search);
  const param = params.get("ticker");
  const qParam = params.get("quarter");
  const cParam = params.get("compare");
  if (param && /^[A-Za-z]{1,10}$/.test(param.trim())) {
    const baseTicker = param.trim().toUpperCase();
    $("company-search").value = baseTicker;
    if (cParam && /^[A-Za-z]{1,10}$/.test(cParam.trim()) && cParam.trim().toUpperCase() !== baseTicker) {
      pendingAutoCompare = { second: cParam.trim().toUpperCase(), base: baseTicker };
      const cs = $("compare-search");
      if (cs) cs.value = cParam.trim().toUpperCase();
    }
    // getBriefing validates the quarter itself (calendar "Qn YYYY"
    // and fiscal "quarter ended YYYY-MM-DD" both pass); the load
    // path must not pre-filter to calendar labels only, or a
    // shared fiscal link reloads as the latest quarter instead
    // of restoring its saved briefing (Batch 20 fix).
    getBriefing(baseTicker, qParam ? qParam.trim() : "");
  }
} catch { /* a bad share link never breaks the page */ }

// Rail steps + legend: jump to that agent's card. Background last,
// so a CDN failure can never block search or the briefing.
document.querySelectorAll(".loop-leg").forEach((btn) => {
  btn.addEventListener("click", () => {
    const target = $(`card-${btn.dataset.jump}`);
    if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
  });
});
document.querySelectorAll(".baton-step").forEach((step) => {
  step.addEventListener("click", () => {
    const target = $(`card-${step.dataset.agent}`);
    if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
  });
});
// ---- Phase 1 wiring (Features 3, 4, 5) ----
// Find box (Feature 3): input + Prev/Next, wired once; render()
// resets its state per briefing.
const findInput = $("briefing-find-input");
if (findInput) findInput.addEventListener("input", runFind);
const findPrev = $("briefing-find-prev");
if (findPrev) findPrev.addEventListener("click", () => stepFind(-1));
const findNext = $("briefing-find-next");
if (findNext) findNext.addEventListener("click", () => stepFind(1));

// Keyboard shortcuts (Feature 5): "/" focuses search (never
// inserts the "/" character, never fires from inside a field);
// Esc closes one layer per press — popover, then search
// results, then compare results.
document.addEventListener("keydown", (e) => {
  const tag = (e.target && e.target.tagName) || "";
  const inField = /^(INPUT|TEXTAREA|SELECT)$/.test(tag) || (e.target && e.target.isContentEditable);
  if (e.key === "/" && !inField && !e.ctrlKey && !e.metaKey && !e.altKey) {
    e.preventDefault();
    const s = $("company-search");
    if (s) { s.focus(); s.select(); }
    return;
  }
  if (e.key === "Escape") {
    if (popoverOpen()) { closePopover(); return; }
    const cr = $("company-results");
    if (cr && !cr.hidden) { show(cr, false); return; }
    const cpr = $("compare-results");
    if (cpr && !cpr.hidden) { show(cpr, false); return; }
  }
});
// Click-outside closes the popover (openers stopPropagation, so
// the click that opens it never reaches this listener).
document.addEventListener("click", (e) => {
  if (popoverOpen() && popoverEl && !popoverEl.contains(e.target)) closePopover();
});

// Explainer card (Feature 4): first visit only; "Got it" sets
// the dismissal key; the footer link re-shows it (and never
// touches the briefing cache).
const explainerCard = $("explainer-card");
if (explainerCard) {
  try { if (!localStorage.getItem("ame_explainer_dismissed")) show(explainerCard, true); } catch {}
}
const explainerBtn = $("explainer-gotit");
if (explainerBtn) explainerBtn.addEventListener("click", () => {
  try { localStorage.setItem("ame_explainer_dismissed", "1"); } catch {}
  show(explainerCard, false);
});
const explainerAgain = $("explainer-again");
if (explainerAgain) explainerAgain.addEventListener("click", () => {
  try { localStorage.removeItem("ame_explainer_dismissed"); } catch {}
  show(explainerCard, true);
  if (explainerCard) explainerCard.scrollIntoView({ block: "nearest" });
});

// Glossary list (Feature 2): the footer link toggles a full
// list of all eight definitions — the same GLOSSARY text, one
// page section, no new page.
const glossaryList = $("glossary-list");
const glossaryItems = $("glossary-items");
if (glossaryItems) {
  glossaryItems.innerHTML = Object.entries(GLOSSARY).map(([term, def]) =>
    `<div><dt>${esc(term)}</dt><dd>${esc(def)}</dd></div>`).join("");
}
const glossaryLink = $("glossary-link");
if (glossaryLink) glossaryLink.addEventListener("click", () => {
  const hidden = !glossaryList || glossaryList.hidden;
  show(glossaryList, hidden);
  if (hidden && glossaryList) glossaryList.scrollIntoView({ block: "nearest" });
});

initBackground();
