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
  const article = $("briefing");
  // Batch 68 (Feature 10): on a phone the popover becomes a
  // full-width in-flow detail instead of a floating box — directly
  // under the table for claim rows, right after the anchor for
  // inline anchors (glossary terms). The <560px CSS makes it
  // position: static, so the inline top/left are cleared here and
  // it cannot overflow the viewport sideways.
  if (window.matchMedia("(max-width: 560px)").matches && article) {
    const wrap = anchorEl ? anchorEl.closest(".analyst-table-wrap") : null;
    if (wrap) wrap.after(pop);
    else if (anchorEl) anchorEl.after(pop);
    else article.appendChild(pop);
    pop.style.top = "";
    pop.style.left = "";
    return;
  }
  // Position below the anchor, inside the briefing article.
  // Re-append to the article first: a previous mobile open may
  // have moved the shared element under a table.
  if (anchorEl && article) {
    article.appendChild(pop);
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
  // Batch 61: the old label strip ate the spaces around "YoY"
  // ("Revenue YoY growth" -> "Revenuegrowth") and the long labels
  // rotated diagonally. Labels are now the bare metric ("Revenue",
  // "Operating income", "GAAP EPS") and never rotate.
  makeChart("growth", "bar", rows.map((r) => r.metric.replace(/\s*YoY\s*/i, " ").replace(/\s*growth\s*/i, "").replace(/\s+/g, " ").trim()),
    [{ label: "YoY %", data: rows.map((r) => r.valueNum),
      backgroundColor: rows.map((r) => colors[r.kind] || "#71717a"), borderRadius: 6 }],
    { scales: { y: { ticks: { font: { size: 11 } } }, x: { ticks: { font: { size: 11 }, maxRotation: 0 } } } });
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
    // Batch 61: never show a raw unit ("0.3 USD_B"). Money in
    // USD_B renders through fmtMoney ($300M); shares stay in
    // billions; anything else keeps its value + unit.
    ? (latestCell.unit === "USD_B" ? fmtMoney(latestCell.value * 1e9)
      : latestCell.unit === "shares_B" ? `${round1(latestCell.value)}B shares`
      : `${round1(latestCell.value)} ${latestCell.unit || ""}`.trim()) : "—";
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
// Batch 72: the rail states, exactly one per step. `opts.failed`
// marks a step red (the run died there); `opts.paused` freezes a
// step (the stream broke mid-run — it is not running, so it must
// not pulse). Every call re-derives all four steps, so a stale
// failed/paused mark can never survive into a new run.
function setLoop(agent, statusText, opts = {}) {
  const activeIdx = agent ? LOOP_ORDER.indexOf(agent) : -1;
  const failed = opts.failed || null;
  const paused = opts.paused || null;
  document.querySelectorAll(".baton-step").forEach((step) => {
    const a = step.dataset.agent;
    const idx = LOOP_ORDER.indexOf(a);
    const isFailed = a === failed;
    const isPaused = a === paused;
    const isDone = !isFailed && !isPaused && activeIdx >= 0 && idx < activeIdx;
    const isActive = !isFailed && !isPaused && a === agent;
    step.classList.toggle("is-active", isActive);
    step.classList.toggle("is-done", isDone);
    step.classList.toggle("is-failed", isFailed);
    step.classList.toggle("is-paused", isPaused);
    const node = step.querySelector(".baton-node");
    if (node) node.textContent = isFailed ? "✕" : isDone ? "✓" : (node.dataset.letter || "");
  });
  RAIL_CONNS.forEach(([from, , id]) => {
    const el = $(id);
    if (el) el.classList.toggle("is-filled", activeIdx >= 0 && LOOP_ORDER.indexOf(from) < activeIdx);
  });
  const status = $("loop-status");
  if (status) status.textContent = statusText || (agent ? `${LOOP_LABEL[agent]} has the baton.` : "No run yet. Pick a company to start the pipeline.");
}

// Batch 72: the rail must never show a step as running or done
// after the run died. Mark the first unfinished leg red; earlier
// legs keep their done state, later legs stay waiting. When every
// leg is already done, the failure is past the rail — show the
// line complete instead of blaming a step.
function markRunFailed() {
  const failed = AGENT_ORDER.find((a) => { const el = card(a); return !el || el.dataset.state !== "done"; });
  if (!failed) { setLoop("conductor", "Run stopped after every step finished."); return; }
  setLoop(failed, `${LOOP_LABEL[failed]} failed — run stopped.`, { failed });
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
  setConductorState("idle");
  const retry = $("error-retry");
  if (retry) retry.hidden = true;
  setLoop(null, "Starting the pipeline.");
  clearCharts();
}

// Batch 72: the conductor strip is the one live status line.
// `state` drives the dot and the strip's left border: running
// (amber, pulsing), done (green), alert (red dot, amber border —
// the established "stopped, not a crash" accent), idle (muted).
// Omitting state leaves the current state alone, so call sites
// that only carry text keep working.
function setConductorState(state) {
  const strip = $("conductor-strip");
  const dot = $("conductor-dot");
  if (strip) {
    strip.classList.toggle("is-running", state === "running");
    strip.classList.toggle("is-done", state === "done");
    strip.classList.toggle("is-alert", state === "alert");
  }
  if (dot) {
    dot.classList.toggle("is-running", state === "running");
    dot.classList.toggle("is-done", state === "done");
    dot.classList.toggle("is-alert", state === "alert");
  }
}

function setConductor(text, detail, state) {
  $("conductor-status").textContent = text;
  if (detail !== undefined) $("conductor-detail").textContent = detail;
  if (state) setConductorState(state);
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

// Batch 72: one place that turns a stream event into the plain-words
// status line. Pure (no DOM) so the harness can assert it directly;
// onStreamEvent and runStream call it instead of duplicating text.
// The status always names what is happening RIGHT NOW, from the
// event actually received — never a guessed stage. `rail.agent` is
// the step the rail highlights; `rail.failed` / `rail.paused` mark
// it red / frozen instead. `ctx` carries run context the event
// alone does not have (elapsed seconds, the working agent).
function runStatusForEvent(name, ev = {}, ctx = {}) {
  const issues = ev.issue_list || [];
  switch (name) {
    case "run_started":
      // No new information beyond "the server accepted the run":
      // the text set on click stays; only the dot starts pulsing.
      return { status: null, detail: null, state: "running", rail: null };
    case "scout_started":
      return { status: "Fetching the earnings filing from SEC EDGAR…", detail: "Step 1 of 4 · Next: Analyst · Usually 30–90s", state: "running", rail: { agent: "scout" } };
    case "scout_done": {
      const facts = ev.fact_list || [];
      return { status: "Checking the numbers…", detail: `Step 2 of 4 · ${facts.length} facts from the filing · Next: Critic`, state: "running", rail: { agent: "analyst" } };
    }
    case "analyst_done": {
      const claims = ev.claim_list || [];
      return { status: "Re-checking every claim…", detail: `Step 3 of 4 · ${claims.length} claims to verify · Next: Writer`, state: "running", rail: { agent: "critic" } };
    }
    case "critic_attempt":
      if (ev.verdict === "PASS") {
        return { status: "Writing the story…", detail: "Step 4 of 4 · Next: briefing", state: "running", rail: { agent: "writer" } };
      }
      return { status: "Revising the claims…", detail: `Critic found ${issues.length} issue${issues.length === 1 ? "" : "s"} · Attempt ${ev.attempt} · Re-checking after the fix`, state: "running", rail: { agent: "analyst" } };
    case "writer_done":
      return { status: "Assembling the briefing…", detail: "Step 4 of 4 · Almost done", state: "running", rail: { agent: "conductor" } };
    case "briefing":
      return { status: "Done — briefing ready", detail: `Ready in ${ctx.total || "?"}s · 4 of 4 steps`, state: "done", rail: { agent: "conductor" } };
    case "error":
      if (ev.verdict === "FAIL") {
        return { status: "Stopped by check — Critic refused to publish", detail: "The gate worked, not a crash · No briefing published", state: "alert", rail: { agent: "critic", failed: "critic" } };
      }
      if (ev.status === "UPSTREAM_ERROR" || /UPSTREAM_ERROR/.test(ev.error || "")) {
        return { status: "Stopped — the SEC rate-limited the request", detail: "The company's data is fine · Try again in a minute", state: "alert", rail: null };
      }
      return { status: "Pipeline stopped with an error", detail: "The server reported this run failed", state: "alert", rail: null };
    case "connection_lost":
      return { status: "Connection lost — live stream stopped", detail: "Run frozen at its last checkpoint · Resume continues from there", state: "alert", rail: ctx.workingAgent ? { agent: ctx.workingAgent, paused: ctx.workingAgent } : { agent: "conductor" } };
    case "stream_ended":
      return { status: "Connection lost — live stream ended early", detail: "Run frozen at its last checkpoint · Resume continues from there", state: "alert", rail: ctx.workingAgent ? { agent: ctx.workingAgent, paused: ctx.workingAgent } : { agent: "conductor" } };
    default:
      return { status: null, detail: null, state: null, rail: null };
  }
}

function onStreamEvent(ev, ticker) {
  const name = ev.event;
  // Batch 31: the run's id, carried by the first event. The
  // retry button after a break resumes this run instead of
  // restarting it; a fresh run's run_started overwrites it.
  if (name === "run_started") {
    lastRunId = ev.run_id || "";
    // Batch 72: the server accepted the run — the dot starts
    // pulsing now. The text set on click stays (it already says
    // Starting / Resuming).
    setConductorState("running");
    return;
  }
  if (name === "scout_started") {
    const s = runStatusForEvent("scout_started", ev);
    setConductor(s.status, s.detail, s.state);
    setStatus("scout", "working", "");
    workingAgent = "scout";
    setLoop(s.rail.agent, "Scout has the baton — fetching filings.");
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
    const s = runStatusForEvent("scout_done", ev);
    setConductor(s.status, s.detail, s.state);
    setStatus("analyst", "working", "");
    workingAgent = "analyst";
    setLoop(s.rail.agent, `Scout handed over ${facts.length} facts.`);
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
    const s = runStatusForEvent("analyst_done", ev);
    setConductor(s.status, s.detail, s.state);
    setStatus("critic", "working", "");
    workingAgent = "critic";
    setLoop(s.rail.agent, `Analyst handed over ${claims.length} claims.`);
    setHandoverLine("analyst-critic", `Analyst → Critic · ${claims.length} claims${tookText(ev.duration_ms)}`);
    addHandover(`Analyst → Critic: ${claims.length} claims`);
    return;
  }
  if (name === "critic_attempt") {
    const issues = ev.issue_list || [];
    const s = runStatusForEvent("critic_attempt", ev);
    if (ev.verdict === "PASS") {
      const body = issues.length
        ? `<ul class="list">${issues.map((i) => `<li>${esc(issueText(i))}</li>`).join("")}</ul>`
        : `<p class="agent-pass">No issues — every claim re-checked and approved.</p>`;
      setBody("critic", body);
      setStatus("critic", "done", ev.duration_ms ? `took ${secs(ev.duration_ms)}` : "");
      setConductor(s.status, s.detail, s.state);
      setStatus("writer", "working", "");
      workingAgent = "writer";
      setLoop(s.rail.agent, "Critic passed — Writer has the baton.");
      setHandoverLine("critic-writer", `Critic → Writer · PASS${tookText(ev.duration_ms)}`);
      addHandover("Critic → Writer: PASS");
    } else {
      setBody("critic",
        `<p class="agent-fail">Attempt ${ev.attempt} — FAIL. Analyst is revising.</p>`
        + `<ul class="list">${issues.map((i) => `<li>${esc(issueText(i))}</li>`).join("")}</ul>`);
      setStatus("critic", "revising", "");
      setStatus("analyst", "working", "");
      workingAgent = "analyst";
      // Batch 72: the conductor previously kept saying "Critic —
      // re-checking" while the Analyst was revising. The status
      // line now follows the revising step.
      setConductor(s.status, s.detail, s.state);
      setLoop(s.rail.agent, "Critic failed the claims — Analyst is revising.");
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
    const s = runStatusForEvent("writer_done", ev);
    setConductor(s.status, s.detail, s.state);
    workingAgent = null;
    setLoop(s.rail.agent, "Writer handed the story back to the Conductor.");
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
  // Batch 72: the Critic step goes red on the rail (it was left
  // pulsing as "active" after the run died) and the status line
  // carries the refusal in plain words.
  const s = runStatusForEvent("error", { verdict: "FAIL" });
  setConductor(s.status, s.detail, s.state);
  markRunFailed();
  setHandoverLine("critic-writer", "Critic → Writer · blocked — gate refused to publish");
  addHandover("Critic → Conductor: FAIL, briefing stopped");
  $("error-msg").textContent = `No briefing was published for ${ticker}: the Critic found problems `
    + `in the numbers (listed on the Critic card) and refused to approve them. That refusal is `
    + `the gate working, not a crash. Try another company, or try this one again later.`;
  show($("error"), true);
}

function showBriefingError(ticker, message, opts = {}) {
  // Batch 61: an upstream rate limit (SEC 429) is not a
  // not-reported verdict — say so, and offer the retry, because
  // re-running a minute later can succeed. The status arrives
  // on the error event; the POST fallback carries it only in
  // the message text, so match both.
  const isUpstream = opts.status === "UPSTREAM_ERROR" || /UPSTREAM_ERROR/.test(message || "");
  let text = `Could not build a briefing for ${ticker}.\n${message}\n\n`;
  if (isUpstream) {
    text += `The SEC rate-limited the request — the company's data is fine, the request just needs a minute. Try again shortly.`;
  } else {
    text += `If this says Critic FAIL, the agents disagreed about a number and refused to publish — `
      + `that refusal is the product working. If it says NOT_REPORTED_YET, the company has not `
      + `reported its most recent quarter yet. Otherwise, try again in a minute.`;
  }
  $("error-msg").textContent = text;
  // Retry only when re-running could change the outcome: a broken
  // connection or an upstream rate limit, not a server verdict (FAIL / NOT_REPORTED_YET
  // would just reproduce itself).
  const retry = $("error-retry");
  if (retry) retry.hidden = !(opts.retry || isUpstream);
  show($("error"), true);
  // Batch 61: a failed run must not leave a blank page when a
  // saved briefing exists — restore it under the error, with its
  // banner, so the user keeps the last good copy (Nov 12, 2026:
  // a failed MSFT refresh left the page empty because the cache
  // had already been deleted; the cache now survives a failure).
  try {
    const cached = readBriefingCache(ticker, currentQuarter);
    if (cached && cached.briefing) {
      lastScoutFacts = cached.facts || [];
      render(cached.briefing);
      showCacheBanner(ticker, cached, currentQuarter);
    }
  } catch { /* restore is best-effort; the error itself already shows */ }
}

// Returns true when the stream spoke (briefing rendered or an
// error event shown) and false when it failed before any event,
// which is the only case that falls back to POST. onError, when
// given (Feature 17 same-quarter compare), receives the server
// verdict instead of the standalone error UI, so the comparison
// can show that side's error.
async function runStream(ticker, quarter = "", onBriefing = null, resumeRunId = "", onError = null) {
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
            const s = runStatusForEvent("briefing", ev, { total });
            setConductor(s.status, s.detail, s.state);
            setLoop(s.rail.agent, `Briefing complete in ${total}s.`);
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
              return runStream(ticker, quarter, onBriefing, "", onError);
            }
            if (onError) {
              const msg = ev.verdict === "FAIL"
                ? `Critic check failed — no briefing was published for this quarter${ev.issues && ev.issues.length ? ` (${ev.issues.length} issue${ev.issues.length === 1 ? "" : "s"})` : ""}.`
                : (ev.error || "Stream failed");
              onError(msg);
              return true;
            }
            if (ev.verdict === "FAIL") {
              showCriticFail(ticker, ev.issues || []);
            } else {
              // Batch 61: mark EVERY unfinished leg failed, not
              // just the working one — the Nov 12 MSFT run left
              // the rail contradicting the ledger (a leg ticked
              // Done while the run had failed). A leg shows Done
              // only when its *_done event arrived.
              AGENT_ORDER.forEach((a) => {
                const el = card(a);
                if (el && el.dataset.state !== "done") setStatus(a, "failed", "");
              });
              // Batch 72: the rail mirrors the ledger — the first
              // unfinished leg goes red, and the status line says
              // plainly what stopped the run (a rate limit is not
              // a verdict).
              const s = runStatusForEvent("error", ev, { workingAgent });
              setConductor(s.status, s.detail, s.state);
              markRunFailed();
              workingAgent = null;
              showBriefingError(ticker, ev.error || "Stream failed", { status: ev.status });
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
      // Batch 72: the briefing arrived but could not be drawn —
      // say so on the status line instead of leaving the last
      // running step pulsing. The rail stays frozen at its last
      // real state; no resume is offered, it would reproduce it.
      setConductor("Could not display the briefing", e.message, "alert");
      if (onError) { onError(e.message); return true; }
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
      // Batch 72: the rail freezes with it — the working step
      // shows paused, not running — and the status line says the
      // run is frozen, not dead.
      const s = runStatusForEvent("connection_lost", {}, { workingAgent });
      setConductor(s.status, s.detail, s.state);
      if (s.rail.paused) setLoop(s.rail.agent, "Run frozen — resume continues from the last finished step.", { paused: s.rail.paused });
      else setLoop(s.rail.agent, "Run frozen — resume continues from the last finished step.");
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
    const s = runStatusForEvent("stream_ended", {}, { workingAgent });
    setConductor(s.status, s.detail, s.state);
    if (s.rail.paused) setLoop(s.rail.agent, "Run frozen — resume continues from the last finished step.", { paused: s.rail.paused });
    else setLoop(s.rail.agent, "Run frozen — resume continues from the last finished step.");
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
  const total = ((Date.now() - runStartedAt) / 1000).toFixed(1);
  setCheckedLine(total);
  // Batch 72: the POST path previously left the status line on
  // "final briefing only" with a running dot after the briefing
  // arrived. Say it is done — but do not touch the rail: no
  // step-by-step view happened here, so no step may claim Done.
  const s = runStatusForEvent("briefing", {}, { total });
  setConductor(s.status, s.detail, s.state);
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
  // Batch 58: a new save must refresh a visible banner for the
  // same ticker+quarter — the Nov 5 UI pass caught the banner
  // still showing the old saved time (6:12:44 AM) after a fresh
  // run saved. A hidden banner stays hidden; a banner for a
  // different ticker or quarter is untouched.
  const savedAt = Date.now();
  try {
    localStorage.setItem(cacheKey(briefing.ticker, quarter), JSON.stringify({
      briefing, facts: lastScoutFacts || [], savedAt,
    }));
    // Batch 61: a successful save is the moment to clear stale
    // keys for this ticker — the Nov 5 lesson (an older entry
    // resurfacing after a refresh) without the Nov 12 bug
    // (deleting BEFORE the run, so a failed refresh destroyed
    // the only good copy). Keep only the key just written.
    // The cleanup lives in the SAME try: if the save itself
    // throws (a full store), the old copy must survive.
    const keep = cacheKey(briefing.ticker, quarter);
    const prefix = `ame_briefing_${briefing.ticker}_`;
    const stale = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k !== keep && (k.startsWith(prefix) || k === legacyCacheKey(briefing.ticker))) stale.push(k);
    }
    stale.forEach((k) => localStorage.removeItem(k));
  } catch { /* cache is best-effort; a full store never breaks a run */ }
  try {
    const b = $("cache-banner");
    if (b && !b.hidden && b.dataset && b.dataset.ticker === briefing.ticker
        && (b.dataset.quarter || "") === (quarter || "")) {
      showCacheBanner(briefing.ticker, { briefing, savedAt }, quarter);
    }
  } catch { /* banner refresh is best-effort, like the cache */ }
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
  // Batch 58: stamp the banner with its ticker+quarter so a
  // later save can tell whether it is the banner to refresh.
  banner.dataset.ticker = ticker;
  banner.dataset.quarter = quarter || "";
  banner.innerHTML = `Showing a briefing saved ${esc(when)} for ${esc(label)}. `
    + `<button type="button" class="btn-secondary" id="cache-refresh">Refresh for latest data</button>`;
  banner.querySelector("#cache-refresh").addEventListener("click", () => {
    // Batch 61: refresh must NOT delete the saved briefing first.
    // The old handler cleared every key for the ticker, then ran
    // live — so a failed refresh (SEC 429, Nov 12, 2026) destroyed
    // the only good copy. Now the run is forced live (skipping the
    // cache read) and the stale keys are cleared only by a
    // SUCCESSFUL save (saveBriefingCache). A failed refresh leaves
    // the saved copy intact, and showBriefingError restores it.
    hideCacheBanner();
    getBriefing(ticker, quarter, null, "", null, true);
  });
  show(banner, true);
}

function setQuarterButtonsDisabled(disabled) {
  document.querySelectorAll("#quarter-picker button").forEach((b) => { b.disabled = disabled; });
}

async function getBriefing(ticker, quarter = "", onDone = null, resumeRunId = "", onError = null, force = false) {
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
  // A forced run (Refresh button) skips the cache and goes live.
  const cached = readBriefingCache(ticker, quarter);
  if (cached && !force) {
    lastScoutFacts = cached.facts || [];
    try { render(cached.briefing); } catch (e) { const msg = "Could not display the saved briefing: " + (e && e.message ? e.message : String(e)); if (onError) { onError(msg); return; } showBriefingError(ticker, msg); return; }
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
    setConductor("Resuming run — replaying completed steps", "Finished stages replay instantly · Only the remaining stages run live", "running");
  } else {
    setConductor("Starting — Scout is first", "Step 1 of 4 · Next: Analyst · Usually 30–90s", "running");
  }
  startElapsed();
  try {
    let streamed;
    try {
      streamed = await runStream(ticker, quarter, onDone, resumeRunId, onError);
    } catch (e) {
      streamed = false;
    }
    if (!streamed) {
      setConductor("Fetching the final briefing…", "Live stream did not speak — no step-by-step view for this run", "running");
      AGENT_ORDER.forEach((a) => {
        setStatus(a, "waiting", "");
        setBody(a, `<p class="agent-waiting">No step-by-step view — the live stream did not speak, so only the final briefing will appear.</p>`);
      });
      try {
        await runPost(ticker, quarter, onDone);
        stopElapsed();
      } catch (e) {
        stopElapsed();
        if (onError) onError(e.message);
        else {
          // Batch 61: same leg rule as the stream error path —
          // no leg stays Waiting after a failed run.
          AGENT_ORDER.forEach((a) => {
            const el = card(a);
            if (el && el.dataset.state !== "done") setStatus(a, "failed", "");
          });
          workingAgent = null;
          // Batch 72: the status line and the rail say the run
          // failed, in the same plain words as the stream path.
          const s = runStatusForEvent("error", { error: e.message });
          setConductor(s.status, s.detail, s.state);
          markRunFailed();
          showBriefingError(ticker, e.message);
        }
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
  // Batch 61: the retry is a live re-run, never a cache serve —
  // a failed refresh's retry must go live again, not return the
  // saved copy the refresh just failed to replace.
  getBriefing(currentTicker, currentQuarter, null, lastRunId, null, true);
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
// Feature 18: a shared 3-way link's third company, run once the
// 2-way comparison is on screen (see startCompare's onDone).
let pendingThirdCompare = null;

// Consume a pending auto-compare after the base run finishes.
// finishedTicker is the ticker whose run just ended (cache or
// stream); the guard ties it to the base the link named.
function consumePendingAutoCompare(finishedTicker) {
  if (!pendingAutoCompare) return;
  const { second, base, compareQuarter } = pendingAutoCompare;
  pendingAutoCompare = null;
  if (lastBriefing && lastBriefing.ticker === base && finishedTicker === base) {
    if (compareQuarter) startSameQuarterCompare(compareQuarter);
    else startCompare(second);
  }
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
// Only periods carrying a core-metric fact count as quarter ends:
// the fact list also holds cover-page as-of dates (shares
// outstanding as of 2026-08-21, 2026-05-15, ...), which are not
// quarters — they used to crowd real quarters (Jan 2026) out of
// the top-3 window and invent bogus options ("May 2026").
// (Batch 37, Nov 5, 2026.)
const PICKER_CORE_METRICS = new Set(["total_revenue", "operating_income", "net_income", "gaap_eps"]);
function prevFiscalQuarters(label, facts, count) {
  const m = /^quarter ended (\d{4}-\d{2}-\d{2})$/.exec(label || "");
  if (!m) return [];
  const current = m[1];
  const ends = [...new Set((facts || []).filter((f) => PICKER_CORE_METRICS.has(f.metric)).map((f) => f.period).filter((p) =>
    /^\d{4}-\d{2}-\d{2}$/.test(p || "")))].filter((p) => p < current).sort().reverse();
  return ends.slice(0, count).map((p) => `quarter ended ${p}`);
}

function renderQuarterPicker(label) {
  const wrap = $("quarter-picker");
  const btns = $("quarter-buttons");
  renderFiscalNote();
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

// Feature 22: fiscal calendar note — which months this company's
// quarters end in, from the briefing's own Scout facts only (no
// new fetch). Months come from the last 8 distinct fact periods;
// fewer than 4 periods hides the note (too little evidence for a
// pattern). Irregular periods render as observed — the note never
// states a future quarter-end date and never "corrects" a 52/53
// week calendar.
const FISCAL_MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function fiscalNoteMonths(facts) {
  const periods = [...new Set((facts || []).map((f) => f.period).filter((p) => /^\d{4}-\d{2}-\d{2}$/.test(p || "")))].sort().reverse().slice(0, 8);
  if (periods.length < 4) return null;
  const months = [...new Set(periods.map((p) => Number(p.slice(5, 7))))].sort((a, b) => a - b);
  return months.map((m) => FISCAL_MONTH_NAMES[m - 1]);
}
function renderFiscalNote() {
  const note = $("fiscal-note");
  if (!note) return;
  const months = fiscalNoteMonths(lastScoutFacts);
  if (!months) { note.hidden = true; return; }
  setText(note, `Quarter ends in the latest facts fall in: ${months.join(", ")}.`);
  note.hidden = false;
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

// Feature 18: the aligner is N-way — rows carry a values array,
// one per briefing, so the same code renders 2-way and 3-way
// comparisons. A metric missing from a briefing shows "—".
function alignClaims(...claimLists) {
  const maps = claimLists.map((c) => claimValueMap(c));
  return [...new Set(maps.flatMap((m) => [...m.keys()]))].map((metric) => ({
    metric,
    values: maps.map((m) => (m.has(metric) ? m.get(metric) : "—")),
  }));
}

function headlineValue(claims, test) {
  const map = claimValueMap(claims);
  for (const [metric, value] of map) {
    if (test(metric)) return value;
  }
  return "—";
}

function compareTableHtml(tickers, rows) {
  const head = `<tr><th>Metric</th>${tickers.map((t) => `<th class="num">${esc(t)}</th>`).join("")}</tr>`;
  const body = rows.map((r) =>
    `<tr><td>${esc(r.metric)}</td>${r.values.map((v) => `<td class="num">${esc(v)}</td>`).join("")}</tr>`).join("");
  return `<table class="compare-table"><thead>${head}</thead><tbody>${body}</tbody></table>`;
}

// The current comparison, for the third-company flow and the
// Remove button: the briefings on screen (2 or 3) plus whether
// the pair is a same-ticker compare.
let lastComparison = null;

function renderComparison(base, second, opts = {}) {
  renderComparisonN([base, second], opts);
}

// Feature 18: the N-way renderer — 2-way and 3-way share it.
// The 3-way title is the three tickers, nothing more (no overall
// verdict, no ranking, no "best" column). The quarters line names
// every quarter and warns when they differ.
function renderComparisonN(briefings, opts = {}) {
  const sec = $("comparison");
  if (!sec || !briefings || briefings.length < 2) return;
  const tickers = briefings.map((b) => b.ticker);
  lastComparison = { briefings, sameTicker: !!opts.sameTicker };
  // Feature 7: the tab names the pair (or trio) it shows.
  const title = opts.sameTicker
    ? `${briefings[0].ticker}: ${shortQuarterLabel(briefings[0].quarter_label)} vs ${shortQuarterLabel(briefings[1].quarter_label)}`
    : (briefings.length === 3 ? tickers.join(" vs ") : `Head to head: ${tickers[0]} vs ${tickers[1]}`);
  document.title = `${title} | Earnings Ledger`;
  const quarters = briefings.map((b) => b.quarter_label);
  const allSameQuarter = quarters.every((q) => q === quarters[0]);
  $("comparison-title").textContent = title;
  $("comparison-quarters").textContent = allSameQuarter
    ? (briefings.length === 3
      ? `All three briefings are for ${quarters[0]}. Figures are each briefing's verified claims.`
      : `Both briefings are for ${quarters[0]}. Figures are each briefing's verified claims.`)
    : `Warning: quarters differ (${quarters.join(" vs ")}) — figures are not like-for-like.`;
  $("comparison-verdicts").innerHTML = briefings.map((b, i) =>
    `<div class="compare-verdict"><div class="compare-verdict-head">${logoImg(b.ticker, "logo-img logo-verdict")}<span class="badge badge-primary">${esc(b.ticker)}</span>`
    + (briefings.length === 3 && i === 2
      ? `<button type="button" class="btn-secondary" id="comparison-remove-third">Remove</button>` : "")
    + `</div><p class="body-text">${esc(b.verdict)}</p></div>`).join("");
  const removeBtn = $("comparison-remove-third");
  if (removeBtn) removeBtn.addEventListener("click", () => removeThirdComparison());
  const headlineRows = [
    { metric: "Revenue YoY growth",
      values: briefings.map((b) => headlineValue(b.table, (m) => m === "Revenue YoY growth")) },
    { metric: "Operating margin",
      values: briefings.map((b) => headlineValue(b.table, (m) => m === "Operating margin")) },
    { metric: "EPS vs consensus",
      values: briefings.map((b) => headlineValue(b.table, (m) => m.includes("vs consensus"))) },
  ];
  $("comparison-headline").innerHTML = compareTableHtml(tickers, headlineRows);
  $("comparison-table").innerHTML = compareTableHtml(
    tickers, alignClaims(...briefings.map((b) => b.table)));
  const ub = $("comparison-units");
  if (ub) { ub.innerHTML = ""; show(ub, false); }
  show(sec, true);
  show($("compare-third-box"), briefings.length === 2 && !opts.sameTicker);
  renderUnitEconomics(tickers);
  // The growth race compares companies' revenue paths — it has
  // nothing to draw when both sides are the same company.
  if (opts.sameTicker) {
    show($("growth-race-card"), false);
    destroyChart("growth-race");
  } else {
    renderGrowthRace(tickers);
  }
}

// Feature 18: dropping the third company returns to the 2-way
// view and updates the share link.
function removeThirdComparison() {
  const cur = lastComparison;
  if (!cur || cur.briefings.length !== 3) return;
  const [base, second] = cur.briefings;
  const baseQuarter = currentQuarter;
  renderComparisonN([base, second], { sameTicker: cur.sameTicker });
  lastComparisonLink = `${location.origin}${location.pathname}?ticker=${base.ticker}&compare=${second.ticker}`
    + (baseQuarter ? `&quarter=${encodeURIComponent(baseQuarter)}` : "");
  try {
    const url = new URL(location.href);
    url.searchParams.set("ticker", base.ticker);
    url.searchParams.set("compare", second.ticker);
    url.searchParams.delete("compare2");
    if (baseQuarter) url.searchParams.set("quarter", baseQuarter);
    else url.searchParams.delete("quarter");
    history.replaceState(null, "", url);
  } catch { /* URL sharing is best-effort */ }
}

// Feature 19: growth race chart — revenue trajectories rebased
// to a common start. Common window = the intersection of the
// companies' quarter periods (positive values only); each series
// is indexed to 100 at the first common quarter (the Worker's
// rebase gives % change from first, so indexed = value_pct +
// 100 — same math, no new rebasing). Total growth and CAGR reuse
// the history module's formulas over the common window. Fewer
// than 4 common quarters hides the chart. Series are never
// shifted, stretched, or forward-filled.
function growthRaceData(seriesByTicker) {
  const tickers = Object.keys(seriesByTicker || {});
  if (tickers.length < 2) return null;
  const byEnd = {};
  for (const t of tickers) {
    const m = new Map();
    for (const p of (seriesByTicker[t] || [])) {
      if (p && p.period_end && typeof p.value === "number" && Number.isFinite(p.value) && p.value > 0) m.set(p.period_end, p.value);
    }
    byEnd[t] = m;
  }
  const common = [...byEnd[tickers[0]].keys()].filter((e) => tickers.every((t) => byEnd[t].has(e))).sort();
  if (common.length < 4) return null;
  const first = common[0], last = common[common.length - 1];
  const days = (new Date(last) - new Date(first)) / 86400000;
  const lines = tickers.map((t) => {
    const firstV = byEnd[t].get(first), lastV = byEnd[t].get(last);
    const data = common.map((e) => byEnd[t].get(e) / firstV * 100);
    const totalGrowth = (lastV / firstV - 1) * 100;
    const cagr = days > 0 ? (Math.pow(lastV / firstV, 365.25 / days) - 1) * 100 : null;
    return { ticker: t, data, totalGrowth, cagr };
  });
  return { labels: common.map((e) => quarterLabel(e)), lines };
}

let lastGrowthRacePair = null;
async function renderGrowthRace(tickers) {
  const card = $("growth-race-card");
  if (!card || !tickers || tickers.length < 2) return;
  const pair = tickers.join("|");
  lastGrowthRacePair = pair;
  show(card, false);
  destroyChart("growth-race");
  const fetchHist = async (t) => {
    try {
      const r = await fetch(`${ORCHESTRATOR_URL}/history?ticker=${encodeURIComponent(t)}&metric=total_revenue`);
      return r.ok ? r.json() : null;
    } catch { return null; }
  };
  const payloads = await Promise.all(tickers.map(fetchHist));
  if (lastGrowthRacePair !== pair) return; // superseded
  if (payloads.some((p) => !p)) return;
  const seriesByTicker = {};
  tickers.forEach((t, i) => { seriesByTicker[t] = payloads[i].series || []; });
  const built = growthRaceData(seriesByTicker);
  const empty = $("chart-growth-race-empty");
  if (!built) {
    if (empty) empty.hidden = false;
    show(card, true);
    return;
  }
  if (empty) empty.hidden = true;
  const colors = ["#1d4ed8", "#0f766e", "#b45309"];
  const darkColors = ["#60a5fa", "#2dd4bf", "#f59e0b"];
  const datasets = built.lines.map((line, i) => {
    const growth = line.totalGrowth != null
      ? `${line.totalGrowth >= 0 ? "+" : ""}${line.totalGrowth.toFixed(1)}%` : "—";
    const cagr = line.cagr != null ? `CAGR ${line.cagr.toFixed(1)}%` : "CAGR —";
    return { label: `${line.ticker} (${growth}, ${cagr})`, data: line.data,
      borderColor: themeColor(colors[i % colors.length], darkColors[i % darkColors.length]),
      backgroundColor: "transparent", tension: 0.2, pointRadius: 0 };
  });
  makeChart("growth-race", "line", built.labels, datasets);
  show(card, true);
}

function startCompare(secondTicker) {
  const base = lastBriefing;
  if (!base) return;
  const second = String(secondTicker || "").trim().toUpperCase();
  const note = $("compare-note");
  if (!second) return;
  // Feature 17: picking the base ticker itself switches the box
  // to same-company mode — quarter buttons instead of a refusal.
  if (second === base.ticker) {
    renderSameTickerQuarters();
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
      url.searchParams.delete("compareQuarter");
      url.searchParams.delete("compare2");
      if (baseQuarter) url.searchParams.set("quarter", baseQuarter);
      else url.searchParams.delete("quarter");
      history.replaceState(null, "", url);
    } catch { /* URL sharing is best-effort */ }
    // Feature 18: a shared 3-way link chains the third company
    // once the 2-way comparison is on screen.
    if (pendingThirdCompare) {
      const third = pendingThirdCompare;
      pendingThirdCompare = null;
      startCompare3(third);
    }
  });
}

// Feature 17: same-company quarter compare. The compare box
// switches mode when the search picks the base ticker: it shows
// the base company's quarter buttons (the same prevQuarters /
// prevFiscalQuarters functions as the quarter picker, driven by
// the base briefing's facts) with the prompt "Compare with an
// earlier quarter". Picking a quarter runs that quarter's
// briefing through the existing cache + pipeline path.
function renderSameTickerQuarters() {
  const base = lastBriefing;
  const box = $("compare-results");
  const note = $("compare-note");
  if (!base || !box) return;
  const search = $("compare-search");
  if (search) search.value = "";
  if (note) { note.textContent = `Compare ${base.ticker} with an earlier quarter`; show(note, true); }
  let prev = prevQuarters(base.quarter_label, 3);
  let fiscal = false;
  if (!prev.length) {
    prev = prevFiscalQuarters(base.quarter_label, lastScoutFacts, 3);
    fiscal = prev.length > 0;
  }
  if (!prev.length) {
    box.innerHTML = `<p class="search-empty">No earlier quarters in this briefing's facts to compare with.</p>`;
    show(box, true);
    return;
  }
  box.innerHTML = prev.map((l) =>
    `<button type="button" class="btn-secondary quarter-btn" data-q="${esc(l)}">${esc(fiscal ? shortQuarterLabel(l) : l)}</button>`).join("");
  box.querySelectorAll(".quarter-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      show(box, false);
      startSameQuarterCompare(btn.dataset.q);
    });
  });
  show(box, true);
}

function startSameQuarterCompare(label) {
  const base = lastBriefing;
  const note = $("compare-note");
  if (!base || !label) return;
  // Comparing a quarter with itself is refused inline, like
  // self-compare today.
  if (label === base.quarter_label) {
    if (note) {
      note.textContent = "That's the quarter already shown — pick an earlier one.";
      show(note, true);
    }
    return;
  }
  if (note) show(note, false);
  const baseQuarter = currentQuarter;
  getBriefing(base.ticker, label, (b) => {
    renderComparison(base, b, { sameTicker: true });
    lastComparisonLink = `${location.origin}${location.pathname}?ticker=${base.ticker}&compare=${base.ticker}&compareQuarter=${encodeURIComponent(label)}`
      + (baseQuarter ? `&quarter=${encodeURIComponent(baseQuarter)}` : "");
    try {
      const url = new URL(location.href);
      url.searchParams.set("ticker", base.ticker);
      url.searchParams.set("compare", base.ticker);
      url.searchParams.set("compareQuarter", label);
      if (baseQuarter) url.searchParams.set("quarter", baseQuarter);
      else url.searchParams.delete("quarter");
      history.replaceState(null, "", url);
    } catch { /* URL sharing is best-effort */ }
  }, "", (msg) => {
    renderComparisonError(base, label, msg);
  });
}

// Feature 17 error side: the earlier quarter's briefing failed
// or was NOT_REPORTED_YET. The comparison still renders with
// the base side's figures and the failure named on the second
// side — it never falls back to the latest quarter.
function renderComparisonError(base, quarterLabel, message) {
  const sec = $("comparison");
  if (!sec || !base) return;
  document.title = `${base.ticker}: ${shortQuarterLabel(base.quarter_label)} vs ${shortQuarterLabel(quarterLabel)} | Earnings Ledger`;
  $("comparison-title").textContent = `${base.ticker}: ${shortQuarterLabel(base.quarter_label)} vs ${shortQuarterLabel(quarterLabel)}`;
  $("comparison-quarters").textContent = `Warning: quarters differ (${base.quarter_label} vs ${quarterLabel}) — the earlier quarter's briefing failed, so only the base side has figures. No latest-quarter briefing was substituted.`;
  $("comparison-verdicts").innerHTML =
    `<div class="compare-verdict"><div class="compare-verdict-head">${logoImg(base.ticker, "logo-img logo-verdict")}<span class="badge badge-primary">${esc(base.ticker)}</span></div><p class="body-text">${esc(base.verdict)}</p></div>`
    + `<div class="compare-verdict"><div class="compare-verdict-head"><span class="badge badge-primary">${esc(base.ticker)}</span></div><p class="body-text">${esc(message || "The earlier quarter's briefing could not be built.")}</p></div>`;
  $("comparison-headline").innerHTML = "";
  $("comparison-table").innerHTML = "";
  const ub = $("comparison-units");
  if (ub) { ub.innerHTML = ""; show(ub, false); }
  show($("growth-race-card"), false);
  destroyChart("growth-race");
  show(sec, true);
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

// Feature 18: the third company. Runs sequentially after the
// 2-way comparison (base, then second, then third — no parallel
// pipeline runs). A failed third briefing falls back to the
// completed 2-way comparison with a note naming the failed
// ticker; it never shows a partial third column.
function startCompare3(thirdTicker) {
  const cur = lastComparison;
  const note = $("compare-note");
  if (!cur || cur.briefings.length !== 2) return;
  const [base, second] = cur.briefings;
  const third = String(thirdTicker || "").trim().toUpperCase();
  if (!third) return;
  if (third === base.ticker || third === second.ticker) {
    if (note) {
      note.textContent = "That's a company already in this comparison — pick a different one.";
      show(note, true);
    }
    return;
  }
  if (note) show(note, false);
  const box3 = $("compare-results-3");
  if (box3) show(box3, false);
  const baseQuarter = currentQuarter;
  getBriefing(third, "", (b) => {
    renderComparisonN([base, second, b]);
    lastComparisonLink = `${location.origin}${location.pathname}?ticker=${base.ticker}&compare=${second.ticker}&compare2=${third}`
      + (baseQuarter ? `&quarter=${encodeURIComponent(baseQuarter)}` : "");
    try {
      const url = new URL(location.href);
      url.searchParams.set("ticker", base.ticker);
      url.searchParams.set("compare", second.ticker);
      url.searchParams.set("compare2", third);
      if (baseQuarter) url.searchParams.set("quarter", baseQuarter);
      else url.searchParams.delete("quarter");
      history.replaceState(null, "", url);
    } catch { /* URL sharing is best-effort */ }
  }, "", () => {
    renderComparisonN([base, second]);
    if (note) {
      note.textContent = `${third} could not be compared — showing the two-company comparison.`;
      show(note, true);
    }
  });
}

function renderCompareResults3(matches) {
  const box = $("compare-results-3");
  if (!box) return;
  if (!matches.length) {
    box.innerHTML = `<p class="search-empty">No company matched — try a different spelling, or a ticker like NVDA.</p>`;
  } else {
    box.innerHTML = matches.map((m) =>
      `<button type="button" class="chip search-match" data-ticker="${esc(m.ticker)}">`
      + `${logoImg(m.ticker, "logo-img logo-chip")}${esc(m.name)} (${esc(m.ticker)})</button>`).join("");
    box.querySelectorAll(".search-match").forEach((btn) => {
      btn.addEventListener("click", () => {
        show(box, false);
        const search3 = $("compare-search-3");
        if (search3) search3.value = "";
        startCompare3(btn.dataset.ticker);
      });
    });
  }
  show(box, true);
}

// EPS beat/miss badge (Batch 19): the same consensus claim and
// the same "reported vs forecast" parse as the EPS chart, so the
// badge can never disagree with the chart. Hidden when no
// consensus claim exists; the title carries the two numbers.
// The badge reads the claims of the briefing being rendered,
// passed in explicitly — never module state. (A cached NVDA
// briefing showed MSFT's EPS figures live on Nov 5, 2026: the
// badge had read lastAnalystClaims, which a previous view had
// left behind. Deriving from the briefing kills that whole class
// of staleness.) Hiding also clears the text and tooltip, so a
// stale "Reported … vs consensus …" can never resurface.
function renderBeatMissBadge(claims) {
  const el = $("b-beatmiss");
  if (!el) return;
  const parsed = (claims || []).map(parseClaim);
  const eps = parsed.find((p) => /consensus/i.test(p.metric));
  const m = eps && eps.detail ? eps.detail.match(/\$?([\d.]+)\s*vs\s*\$?([\d.]+)/) : null;
  if (!m) { el.textContent = ""; el.title = ""; show(el, false); return; }
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
    // Batch 61: Nasdaq's SharesOutstandingPCT can exceed 100%
    // (DUOL showed 103.67%) — shares lent out are counted twice.
    // Keep the reported figure, but say so when it is impossible
    // as a plain percentage, instead of presenting it unflagged.
    const pctNum = parseFloat(String(f.ownership_pct).replace(/%$/, ""));
    const flag = (Number.isFinite(pctNum) && pctNum > 100)
      ? " (above 100% — Nasdaq counts lent shares twice, so this is not a share of the company)"
      : "";
    parts.push(`<p class="body-text">Institutional ownership: ${esc(f.ownership_pct)} of ${esc(f.shares_outstanding || "—")} million shares outstanding.${esc(flag)}</p>`);
  }
  const pos = [...(f.positions || []), ...(f.new_sold_out || [])];
  if (pos.length) {
    parts.push("<ul class=\"list\">" + pos.map((p) => `<li>${esc(p.label)} — ${esc(p.holders)} holders, ${esc(p.shares)} shares</li>`).join("") + "</ul>");
  }
  if ((f.top || []).length) {
    // Batch 61: the parenthetical was change_pct — the holder's
    // CHANGE in shares — shown bare after the share count, where
    // it read as an ownership percentage ("2,332,543 shares
    // (2019.569%)"). Label it as the change it is.
    parts.push("<p class=\"body-text\">Largest holders as listed:</p><ul class=\"list\">" + f.top.map((h) => {
      const chg = String(h.change_pct ?? "").replace(/%$/, "");
      const chgText = chg === "" || chg === "—" ? "" : `, ${chg.startsWith("-") ? "" : "+"}${chg}% change in shares`;
      return `<li>${esc(h.owner)} — ${esc(h.shares)} shares${esc(chgText)} as of ${esc(h.date)}</li>`;
    }).join("") + "</ul>");
  }
  return parts.join("");
}

function politiciansCardHtml(rows) {
  if (!rows || !rows.length) return "";
  const items = rows.slice(0, 10).map((r) => {
    // Join only the parts present, keeping the "house TX" shape:
    // an executive-branch row has no party, so "(, executive)"
    // must never render.
    const bits = [];
    if (r.party) bits.push(r.party);
    if (r.chamber) bits.push(r.state ? `${r.chamber} ${r.state}` : r.chamber);
    else if (r.state) bits.push(r.state);
    const who = `${r.name} (${bits.join(", ")})`;
    const type = r.type ? r.type.charAt(0).toUpperCase() + r.type.slice(1) : "";
    return `<li>${esc(who)} — ${esc(type)} ${esc(r.range)}${r.date ? `, traded ${esc(r.date)}` : ""}${r.filed ? `, filed ${esc(r.filed)}` : ""}</li>`;
  }).join("");
  const more = rows.length > 10 ? `<p class="meta">Showing the 10 most recent of ${rows.length} returned.</p>` : "";
  return `<ul class="list">${items}</ul>${more}`;
}

async function renderOwnership(ticker) {
  const sec = $("ownership");
  if (!sec || !ticker) return;
  // Clear stale content before the async fetch: without this,
  // the previous briefing's cards stay visible until this
  // ticker's data arrives, and the section can end up headed
  // with the wrong company (Nov 5, 2026: NVDA's briefing showed
  // "Who's trading MSFT"). The title names the new ticker now;
  // the section hides until apply() shows it with fresh data.
  setText($("ownership-title"), `Who's trading ${ticker}`);
  show(sec, false);
  const apply = (data) => {
    if (ticker !== currentTicker) return; // a newer briefing superseded this fetch
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

// [PHASE2-PURE:trendTableRows]
// Aligns three history series by period_end (newest first, max 8
// rows): revenue, EPS, operating margin (operating income / revenue
// for the same period only), QoQ revenue change vs the previous
// quarter. A missing quarter is null ("—" on render), never
// interpolated or carried forward. QoQ needs the prior quarter in
// the revenue series to be consecutive (70–110 days earlier); a
// gap yields null.
function trendTableRows(revSeries, epsSeries, opincSeries) {
  const byEnd = (series) => {
    const m = new Map();
    (series || []).forEach((p) => {
      if (p && p.period_end && typeof p.value === "number" && Number.isFinite(p.value)) m.set(p.period_end, p.value);
    });
    return m;
  };
  const rev = byEnd(revSeries), eps = byEnd(epsSeries), op = byEnd(opincSeries);
  const ends = [...new Set([...rev.keys(), ...eps.keys(), ...op.keys()])].sort().reverse().slice(0, 8);
  const revSorted = [...rev.keys()].sort();
  return ends.map((end) => {
    const r = rev.get(end), e = eps.get(end), o = op.get(end);
    let qoq = null;
    if (r !== undefined) {
      const i = revSorted.indexOf(end);
      if (i > 0) {
        const prevEnd = revSorted[i - 1];
        const gapDays = (new Date(end) - new Date(prevEnd)) / 86400000;
        const prev = rev.get(prevEnd);
        if (prev !== undefined && prev !== 0 && gapDays >= 70 && gapDays <= 110) {
          qoq = (r - prev) / Math.abs(prev) * 100;
        }
      }
    }
    return { period_end: end,
             revenue: r === undefined ? null : r,
             eps: e === undefined ? null : e,
             margin: (r !== undefined && o !== undefined && r !== 0) ? (o / r) * 100 : null,
             qoq };
  });
}
// [/PHASE2-PURE]

function quarterShortLabel(iso) {
  const m = /^(\d{4})-(\d{2})-\d{2}$/.exec(String(iso || ""));
  if (!m) return iso || "";
  return `${SHORT_MONTHS[Number(m[2]) - 1]} ${m[1]}`;
}

// Feature 12: recent filings card — fire-and-forget like
// ownership; renders when its fetch returns, stays hidden if the
// fetch fails or returns nothing usable.
async function renderFilings(ticker) {
  const sec = $("sec-filings");
  if (!sec || !ticker || !lastBriefing || lastBriefing.ticker !== ticker) return;
  show(sec, false);
  try {
    const resp = await fetch(`${ORCHESTRATOR_URL}/filings?ticker=${encodeURIComponent(ticker)}`);
    if (!resp.ok) return;
    const data = await resp.json();
    if (!data || data.error || !data.filings) return;
    if (!lastBriefing || lastBriefing.ticker !== ticker) return; // stale
    const all = [...(data.filings["10-K"] || []), ...(data.filings["10-Q"] || []), ...(data.filings["8-K"] || [])]
      .sort((a, b) => String(b.filingDate || "").localeCompare(String(a.filingDate || "")));
    if (!all.length) return;
    setHTML($("b-filings"), all.map((f) =>
      `<li><strong>${esc(f.form)}</strong> · report ${esc(f.reportDate || "—")} · filed ${esc(f.filingDate || "—")} · <a href="${esc(f.url)}" target="_blank" rel="noopener">Open filing</a></li>`).join(""));
    show(sec, true);
  } catch { /* hide on failure */ }
}

// Feature 24: news around earnings — headlines ±7 days around
// the briefing's report date, linked and dated, no summary.
// The route derives the report date itself (the Briefing
// schema does not carry it). An empty list hides the card.
// Headlines are the publishers' words — never cited as
// briefing sources, and no number is ever pulled from one.
async function renderNews(ticker) {
  const sec = $("sec-news");
  if (!sec || !ticker || !lastBriefing || lastBriefing.ticker !== ticker) return;
  show(sec, false);
  try {
    const resp = await fetch(`${ORCHESTRATOR_URL}/news?ticker=${encodeURIComponent(ticker)}`);
    if (!resp.ok) return;
    const data = await resp.json();
    if (!data || data.error || !lastBriefing || lastBriefing.ticker !== ticker) return; // stale
    const rows = data.news || [];
    if (!rows.length) return;
    setHTML($("b-news"), rows.map((n) =>
      `<li><a href="${esc(n.url)}" target="_blank" rel="noopener">${esc(n.title)}</a> — ${esc(n.publisher || "—")} · ${esc(n.published || "—")}</li>`).join(""));
    show(sec, true);
  } catch { /* hide on failure */ }
}

// Feature 13: quarter trend table — three history series in
// parallel, aligned by period end. The whole card hides if any
// fetch fails; a metric missing for a quarter shows "—".
async function renderTrendTable(ticker) {
  const sec = $("sec-trend-table");
  if (!sec || !ticker || !lastBriefing || lastBriefing.ticker !== ticker) return;
  show(sec, false);
  const fetchHist = async (m) => {
    try {
      const r = await fetch(`${ORCHESTRATOR_URL}/history?ticker=${encodeURIComponent(ticker)}&metric=${encodeURIComponent(m)}`);
      return r.ok ? r.json() : null;
    } catch { return null; }
  };
  const [rev, eps, op] = await Promise.all([
    fetchHist("total_revenue"), fetchHist("gaap_eps"), fetchHist("operating_income"),
  ]);
  if (!lastBriefing || lastBriefing.ticker !== ticker) return; // stale
  if (!rev || !eps || !op) return;
  const rows = trendTableRows(rev.series, eps.series, op.series);
  if (!rows.length) return;
  const fmtEps = (v) => (v == null ? "—" : `$${v.toFixed(2)}`);
  const fmtMargin = (v) => (v == null ? "—" : `${v.toFixed(1)}%`);
  setHTML($("b-trend-table"),
    `<thead><tr><th>Quarter</th><th>Revenue</th><th>EPS</th><th>Operating margin</th><th>QoQ revenue</th></tr></thead><tbody>` +
    rows.map((r) =>
      `<tr><td>Q ended ${esc(quarterShortLabel(r.period_end))}</td><td>${esc(fmtMoney(r.revenue))}</td><td>${esc(fmtEps(r.eps))}</td><td>${esc(fmtMargin(r.margin))}</td><td>${esc(fmtPct(r.qoq))}</td></tr>`).join("") +
    `</tbody>`);
  show(sec, true);
}

// Feature 14: dividend card — last 4 Cash dividends + trailing
// yield, from the Orchestrator's /dividends route. Hides when the
// company pays none, when the fetch fails, or when the ticker
// changes mid-flight. The yield line hides when the close is
// missing; the next declared ex-date never enters the sum.
async function renderDividends(ticker) {
  const sec = $("chart-dividend-card");
  if (!sec || !ticker || !lastBriefing || lastBriefing.ticker !== ticker) return;
  show(sec, false);
  try {
    const resp = await fetch(`${ORCHESTRATOR_URL}/dividends?ticker=${encodeURIComponent(ticker)}`);
    if (!resp.ok) return;
    const data = await resp.json();
    if (!data || data.error || !lastBriefing || lastBriefing.ticker !== ticker) return; // stale
    const rows = data.rows || [];
    if (!rows.length) return;
    const fmtAmt = (v) => (Number.isFinite(Number(v)) ? `$${Number(v).toFixed(2)}` : "—");
    setHTML($("b-dividends"),
      `<thead><tr><th>Ex-date</th><th>Amount</th><th>Pay date</th></tr></thead><tbody>` +
      rows.map((r) =>
        `<tr><td>${esc(r.ex_date || "—")}</td><td>${fmtAmt(r.amount)}</td><td>${esc(r.pay_date || "—")}</td></tr>`).join("") +
      `</tbody>`);
    const y = $("b-dividend-yield");
    if (data.trailing_yield != null && Number.isFinite(Number(data.trailing_yield))) {
      const close = Number.isFinite(Number(data.last_close)) ? ` ÷ last close ${fmtAmt(data.last_close)}` : "";
      setText(y, `Trailing yield: ${Number(data.trailing_yield).toFixed(1)}% (sum of last 4 dividends${close})`);
      y.hidden = false;
    } else { y.hidden = true; }
    const n = $("b-dividend-next");
    if (data.next_ex_date) {
      setText(n, `Next ex-date (declared): ${esc(data.next_ex_date.ex_date || "—")} — ${fmtAmt(data.next_ex_date.amount)}`);
      n.hidden = false;
    } else { n.hidden = true; }
    show(sec, true);
  } catch { /* hide on failure */ }
}

// Feature 15: shareholder yield card — (trailing buybacks +
// trailing dividends) / market cap, all three inputs shown so
// the ratio can be rechecked by hand. A null payload (any input
// missing) hides the card, like the dividend card hides on
// empty rows.
async function renderShareholderYield(ticker) {
  const sec = $("chart-yield-card");
  if (!sec || !ticker || !lastBriefing || lastBriefing.ticker !== ticker) return;
  show(sec, false);
  try {
    const resp = await fetch(`${ORCHESTRATOR_URL}/shareholder-yield?ticker=${encodeURIComponent(ticker)}`);
    if (!resp.ok) return;
    const data = await resp.json();
    if (!data || data.error || data.shareholder_yield == null || !lastBriefing || lastBriefing.ticker !== ticker) return; // stale
    setText($("b-yield-value"), `Shareholder yield: ${Number(data.shareholder_yield).toFixed(1)}%`);
    setText($("b-yield-inputs"),
      `Buybacks (trailing 4 quarters): ${fmtMoney(data.buybacks_trailing_usd)} · Dividends (trailing 4 quarters): ${fmtMoney(data.dividends_trailing_usd)} · Market cap: ${fmtMoney(data.market_cap_usd)}`);
    const n = $("b-yield-note");
    if (data.approximation_note) { setText(n, data.approximation_note); n.hidden = false; }
    else { n.hidden = true; }
    show(sec, true);
  } catch { /* hide on failure */ }
}

// Feature 20: past earnings reactions table — the close around
// each of the last four earnings reports. A quarter with no
// close after the report date yet shows "—" for Close after
// and Change %. Fewer than 2 rows hides the card; omitted
// quarters are named in the footer.
async function renderPastReactions(ticker) {
  const sec = $("sec-past-reactions");
  if (!sec || !ticker || !lastBriefing || lastBriefing.ticker !== ticker) return;
  show(sec, false);
  try {
    const resp = await fetch(`${ORCHESTRATOR_URL}/past-reactions?ticker=${encodeURIComponent(ticker)}`);
    if (!resp.ok) return;
    const data = await resp.json();
    if (!data || data.error || !lastBriefing || lastBriefing.ticker !== ticker) return; // stale
    const rows = data.rows || [];
    if (rows.length < 2) return;
    const fmtClose = (v) => (v == null ? "—" : `$${Number(v).toFixed(2)}`);
    const fmtChg = (v) => (v == null ? "—" : `${v > 0 ? "+" : ""}${Number(v).toFixed(1)}%`);
    setHTML($("b-past-reactions"),
      `<thead><tr><th>Quarter ended</th><th>Report date</th><th>Close before</th><th>Close after</th><th>Change %</th></tr></thead><tbody>` +
      rows.map((r) =>
        `<tr><td>${esc(r.quarter_end || "—")}</td><td>${esc(r.report_date || "—")}</td><td>${fmtClose(r.close_before)}</td><td>${fmtClose(r.close_after)}</td><td>${fmtChg(r.change_pct)}</td></tr>`).join("") +
      `</tbody>`);
    const f = $("b-past-reactions-footer");
    const omitted = data.omitted ? ` ${data.omitted} quarter${data.omitted === 1 ? "" : "s"} omitted (no earnings 8-K identified).` : "";
    setText(f, `Regular-session closes from Nasdaq (free, unadjusted — a split or large dividend between the two days can distort the move). Daily closes cannot show the after-hours move.${omitted}`);
    f.hidden = false;
    show(sec, true);
  } catch { /* hide on failure */ }
}

// Feature 16: cash-return chart data — buybacks + dividends per
// quarter. Quarters are the buyback series' quarters (up to 12,
// newest last); a dividend belongs to the quarter whose window
// (previous buyback period_end, this period_end] its ex-date
// falls in. The dividends segment uses the nearest shares-series
// period <= the quarter end; with no such period the segment is
// omitted and the quarter is flagged. A quarter with neither
// segment is omitted from the chart (never drawn as zero). Fewer
// than 2 quarters with any data hides the card.
function cashReturnQuarters(buybacksSeries, sharesSeries, dividendRows) {
  const bb = (buybacksSeries || []).filter((p) => p && Number.isFinite(Number(p.value)) && /^\d{4}-\d{2}-\d{2}$/.test(p.period_end || ""))
    .sort((a, b) => String(a.period_end).localeCompare(String(b.period_end)));
  if (!bb.length) return null;
  const shares = (sharesSeries || []).filter((p) => p && Number.isFinite(Number(p.value)) && /^\d{4}-\d{2}-\d{2}$/.test(p.period_end || ""))
    .sort((a, b) => String(a.period_end).localeCompare(String(b.period_end)));
  const divs = (dividendRows || []).filter((r) => r && Number.isFinite(Number(r.amount)) && /^\d{4}-\d{2}-\d{2}$/.test(r.ex_date || ""))
    .sort((a, b) => String(a.ex_date).localeCompare(String(b.ex_date)));
  const built = bb.map((q, i) => {
    const end = q.period_end;
    const prev = i > 0 ? bb[i - 1].period_end : null;
    const start = prev || new Date(new Date(end + "T00:00:00Z").getTime() - 100 * 86400000).toISOString().slice(0, 10);
    const perShare = divs.filter((d) => d.ex_date > start && d.ex_date <= end)
      .reduce((s, d) => s + Number(d.amount), 0);
    let sharesForQ = null;
    for (const s of shares) { if (s.period_end <= end) sharesForQ = Number(s.value); else break; }
    const dividendsUsd = perShare > 0 && sharesForQ != null ? perShare * sharesForQ : null;
    const dividendsOmitted = perShare > 0 && sharesForQ == null;
    return { period_end: end, buybacks_usd: Number(q.value), dividends_usd: dividendsUsd, dividends_omitted: dividendsOmitted };
  });
  const window = built.slice(-12);
  let omitted = 0;
  const quarters = window.filter((q) => {
    if (!q.buybacks_usd && q.dividends_usd == null) { omitted++; return false; }
    return true;
  });
  if (quarters.length < 2) return null;
  return { quarters, omitted };
}

async function renderCashReturn(ticker) {
  const sec = $("chart-cashreturn-card");
  if (!sec || !ticker || !lastBriefing || lastBriefing.ticker !== ticker) return;
  show(sec, false);
  destroyChart("cashreturn");
  const fetchHist = async (m) => {
    try {
      const r = await fetch(`${ORCHESTRATOR_URL}/history?ticker=${encodeURIComponent(ticker)}&metric=${encodeURIComponent(m)}`);
      return r.ok ? r.json() : null;
    } catch { return null; }
  };
  const fetchDivs = async () => {
    try {
      const r = await fetch(`${ORCHESTRATOR_URL}/dividends?ticker=${encodeURIComponent(ticker)}`);
      return r.ok ? r.json() : null;
    } catch { return null; }
  };
  const [bb, sh, dv] = await Promise.all([fetchHist("buybacks"), fetchHist("shares_outstanding"), fetchDivs()]);
  if (!lastBriefing || lastBriefing.ticker !== ticker) return; // stale
  if (!bb || !sh || !dv) return;
  const built = cashReturnQuarters(bb.series, sh.series, dv.rows);
  if (!built) return;
  const labels = built.quarters.map((q) => quarterLabel(q.period_end));
  const bbData = built.quarters.map((q) => q.buybacks_usd / 1e9);
  const dvData = built.quarters.map((q) => q.dividends_usd == null ? null : q.dividends_usd / 1e9);
  setChartEmpty("cashreturn", false);
  makeChart("cashreturn", "bar", labels, [
    { label: "Buybacks ($B)", data: bbData, backgroundColor: "#1d4ed8" },
    { label: "Dividends ($B)", data: dvData, backgroundColor: "#60a5fa" },
  ], {
    scales: { x: { stacked: true }, y: { stacked: true, ticks: { callback: (v) => `$${v}B` } } },
    plugins: { tooltip: { callbacks: { label: (ctx) => {
      const q = built.quarters[ctx.dataIndex];
      const seg = ctx.datasetIndex === 0
        ? `Buybacks: ${fmtMoney(q.buybacks_usd)}`
        : `Dividends: ${q.dividends_usd == null ? "—" : fmtMoney(q.dividends_usd)}`;
      const total = q.buybacks_usd + (q.dividends_usd || 0);
      const flag = q.dividends_omitted && ctx.datasetIndex === 0
        ? " (dividends segment omitted — no share count for this quarter)" : "";
      return `${seg} · Total: ${fmtMoney(total)}${flag}`;
    } } } },
  });
  const foot = $("b-cashreturn-footer");
  const parts = ["Dividends per quarter = per-share dividends in the quarter × the nearest reported share count at or before the quarter end — an approximation."];
  if (built.omitted) parts.push(`${built.omitted} quarter${built.omitted === 1 ? "" : "s"} with no buybacks or dividends are not shown.`);
  setText(foot, parts.join(" "));
  foot.hidden = false;
  show(sec, true);
}

// Feature 18: the units block is N-way — one line per company,
// "—" for a company missing an input, and the block still
// renders when at least two companies have values (for the 2-way
// case that is the same as before: both must have values).
async function renderUnitEconomics(tickers) {
  const box = $("comparison-units");
  if (!box) return;
  const fetchHist = async (t, m) => {
    try {
      const r = await fetch(`${ORCHESTRATOR_URL}/history?ticker=${encodeURIComponent(t)}&metric=${encodeURIComponent(m)}`);
      return r.ok ? r.json() : null;
    } catch { return null; }
  };
  const payloads = await Promise.all(tickers.flatMap((t) => [fetchHist(t, "total_revenue"), fetchHist(t, "headcount")]));
  const perEmployee = (rev, hc) => {
    const r = rev && rev.series && rev.series.length ? rev.series[rev.series.length - 1] : null;
    const h = hc && hc.series && hc.series.length ? hc.series[hc.series.length - 1] : null;
    if (!r || !h || !h.value) return null;
    return { value: r.value / h.value, revLabel: r.label, revValue: r.value,
      hcLabel: h.label, hcValue: h.value };
  };
  const values = tickers.map((t, i) => perEmployee(payloads[i * 2], payloads[i * 2 + 1]));
  const have = values.filter((v) => v != null).length;
  if (have < 2) { show(box, false); box.innerHTML = ""; return; }
  const lines = tickers.map((t, i) => {
    const v = values[i];
    if (!v) return `${esc(t)}: —`;
    return `${esc(t)}: ${fmtMoney(v.value)} revenue per employee — ${fmtMoney(v.revValue)} revenue (${esc(v.revLabel)}) ÷ ${esc(Number(v.hcValue).toLocaleString())} employees (${esc(v.hcLabel)}).`;
  });
  box.innerHTML = `<h4>Per unit</h4><p class="body-text">${lines.join("<br>")}</p>`
    + `<p class="meta">Revenue is the latest quarterly XBRL figure; headcount is the latest DEI-tagged 10-K figure. The block shows when at least two companies have both inputs; a company missing one shows "—".</p>`;
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
  renderBeatMissBadge(briefingClaims);
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
  renderFilings(b.ticker);
  renderNews(b.ticker);
  renderTrendTable(b.ticker);
  renderDividends(b.ticker);
  renderShareholderYield(b.ticker);
  renderPastReactions(b.ticker);
  renderCashReturn(b.ticker);
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
  // Shareable link: if the run fell back to a different quarter
  // than requested (an unrecognized label falls back to the most
  // recent quarter server-side), the URL must name the briefing
  // actually shown, not the request — otherwise a shared link
  // replays the fallback and still names the wrong quarter
  // (Nov 5, 2026: NVDA's URL said "quarter ended 2025-07-27"
  // while the page showed 2026-07-26).
  if (currentQuarter && b.quarter_label && b.quarter_label !== currentQuarter) {
    try {
      const url = new URL(location.href);
      url.searchParams.set("quarter", b.quarter_label);
      history.replaceState(null, "", url);
      currentQuarter = b.quarter_label;
    } catch { /* URL sharing is best-effort */ }
  }
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
// Batch 63: the in-flight AI search, abortable — a newer search
// cancels the old one instead of queueing behind a lock.
let searchAbort = null;

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

// Batch 63: ticker search was slow because every Search/Enter went
// to the AI Search LLM round trip first (seconds), while a lock
// froze the instant suggestions for the whole wait — and a ticker
// the local directory already holds never needed the network at
// all. Local first now: a directory match renders immediately and
// skips AI Search; the index is only consulted when the directory
// has nothing, for fuzzy and description-based queries.
function localMatches(query, dir) {
  const q = query.toLowerCase();
  return (dir || []).filter((c) =>
    c.name.toLowerCase().includes(q) || c.ticker.toLowerCase().includes(q),
  ).slice(0, 5);
}

async function searchCompanies() {
  const query = $("company-search").value.trim();
  const box = $("company-results");
  if (!query) return;
  if (searchCache.has(query)) {
    const hit = searchCache.get(query);
    renderSearchResults(hit.matches, query, hit.fallback);
    return;
  }
  // Local first: instant, no network. A ticker or name the
  // directory holds never waits on the AI round trip.
  const dir = await loadDirectory();
  const local = localMatches(query, dir);
  if (local.length) {
    searchCache.set(query, { matches: local, fallback: false });
    renderSearchResults(local, query);
    return;
  }
  // No local match: ask the index. A newer search aborts the
  // in-flight one instead of dropping silently behind a lock,
  // and an 8s timeout falls through to the unavailable note
  // rather than hanging on "Searching…" forever.
  if (searchAbort) searchAbort.abort();
  const ctrl = new AbortController();
  searchAbort = ctrl;
  const timer = setTimeout(() => ctrl.abort(), 8000);
  logSearch(query, null);
  box.innerHTML = `<p class="search-empty">Searching…</p>`;
  show(box, true);
  try {
    const resp = await fetch(SEARCH_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: [{ role: "user", content: query }] }),
      signal: ctrl.signal,
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
      // Batch 18: the index found nothing — the local directory
      // was already checked above and is empty for this query,
      // so there is no local fallback to offer; the empty state
      // carries the did-you-mean suggestions instead.
      renderSearchResults([], query, true);
      return;
    }
    renderSearchResults(matches, query);
  } catch (e) {
    // Superseded by a newer search: stay silent, it renders.
    if (ctrl.signal.aborted && searchAbort !== ctrl) return;
    box.innerHTML = `<p class="search-empty">Company search is unavailable right now (${esc(e.message)}) — try a different spelling, or pick a company from the instant matches above.</p>`;
    show(box, true);
  } finally {
    clearTimeout(timer);
    if (searchAbort === ctrl) searchAbort = null;
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

// Feature 11, Batch 66: earnings calendar as a month grid —
// who reports, on which day, before the open or after the
// close, with the company logo. Runs on every load for the
// current month; ‹ › move months, Today jumps back. Clicking
// an entry runs that company's latest briefing. A failed day
// is marked unavailable in its cell, never shown as empty;
// days with no directory company show just the date number.
// Non-directory tickers are dropped silently. The timing pill
// comes from Nasdaq's `time` field ("before"/"after"); a row
// without one gets no pill, never a guessed time.
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const CAL_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const CAL_MAX_VISIBLE = 3;
let calMonth = null; // "YYYY-MM"; null = current month
function calMonthParts(monthIso) {
  const d = monthIso ? new Date(`${monthIso}-01T00:00:00`) : new Date();
  return { y: d.getFullYear(), m: d.getMonth() };
}
function calShift(monthIso, delta) {
  const { y, m } = calMonthParts(monthIso);
  const d = new Date(y, m + delta, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}
function calTimePill(time) {
  if (time === "before") return `<span class="cal-pill cal-pill-before" title="Reports before market open">Before open</span>`;
  if (time === "after") return `<span class="cal-pill cal-pill-after" title="Reports after market close">After close</span>`;
  return "";
}
function calEntryHtml(r, names) {
  const t = String(r.ticker || "").toUpperCase();
  const name = esc(names[t] || r.name || t);
  return `<button type="button" class="cal-entry" data-ticker="${esc(t)}" title="${name} — click to run the briefing">${logoImg(t, "logo-img logo-cal")}<span class="cal-ticker">${esc(t)}</span>${calTimePill(r.time)}</button>`;
}
function calDayCell(day, tickers, names, todayIso) {
  const d = new Date(`${day.date}T00:00:00`);
  const num = d.getDate();
  const isToday = day.date === todayIso;
  if (day.error) return `<div class="cal-cell${isToday ? " cal-today" : ""}"><span class="cal-num">${num}</span><span class="cal-err">Unavailable</span></div>`;
  const mine = (day.rows || []).filter((r) => tickers.has(String(r.ticker || "").toUpperCase()));
  const visible = mine.slice(0, CAL_MAX_VISIBLE);
  const extra = mine.length - visible.length;
  return `<div class="cal-cell${isToday ? " cal-today" : ""}"><span class="cal-num">${num}</span>` +
    visible.map((r) => calEntryHtml(r, names)).join("") +
    (extra > 0 ? `<button type="button" class="cal-more" data-date="${esc(day.date)}">+${extra} more</button>` : "") +
    `</div>`;
}
function calGridHtml(monthIso, days, tickers, names, todayIso) {
  const { y, m } = calMonthParts(monthIso);
  const firstWeekday = new Date(y, m, 1).getDay();
  const blanks = Array.from({ length: firstWeekday }, () => `<div class="cal-cell cal-blank"></div>`).join("");
  const cells = days.map((day) => calDayCell(day, tickers, names, todayIso)).join("");
  return `<div class="cal-nav"><button type="button" class="cal-nav-btn" data-shift="-1" aria-label="Previous month">‹</button><span class="cal-title">${CAL_MONTHS[m]} ${y}</span><button type="button" class="cal-nav-btn" data-shift="1" aria-label="Next month">›</button><button type="button" class="cal-today-btn">Today</button>${calViewToggleHtml()}</div>` +
    `<div class="cal-weekdays">${WEEKDAYS.map((w) => `<span>${w}</span>`).join("")}</div>` +
    `<div class="cal-grid">${blanks}${cells}</div>` +
    `<p class="cal-legend"><span><span class="cal-pill cal-pill-before">Before open</span> reports before the market opens</span><span><span class="cal-pill cal-pill-after">After close</span> reports after the market closes</span></p>`;
}
async function renderCalendarGrid() {
  const box = $("calendar-grid");
  if (!box) return;
  const monthIso = calMonth || (() => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`; })();
  box.innerHTML = `<p class="meta">Loading calendar…</p>`;
  try {
    const [resp, dir] = await Promise.all([
      fetch(`${ORCHESTRATOR_URL}/calendar?month=${monthIso}`),
      loadDirectory(),
    ]);
    if (!resp.ok) throw new Error("calendar fetch failed");
    const data = await resp.json();
    const tickers = new Set((dir || []).map((c) => String(c.ticker || "").toUpperCase()));
    const names = {};
    for (const c of dir || []) names[String(c.ticker || "").toUpperCase()] = c.name || c.ticker;
    const today = new Date();
    const todayIso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
    box.innerHTML = calGridHtml(data.month || monthIso, data.days || [], tickers, names, todayIso);
    box.querySelectorAll(".cal-nav-btn").forEach((btn) => {
      btn.addEventListener("click", () => { calMonth = calShift(calMonth, Number(btn.dataset.shift)); renderCalendarGrid(); });
    });
    box.querySelector(".cal-today-btn").addEventListener("click", () => { calMonth = null; renderCalendarGrid(); });
    wireCalViewToggle(box);
    box.querySelectorAll(".cal-entry").forEach((btn) => {
      btn.addEventListener("click", () => getBriefing(btn.dataset.ticker));
    });
    box.querySelectorAll(".cal-more").forEach((btn) => {
      btn.addEventListener("click", () => {
        const cell = btn.closest(".cal-cell");
        const day = (data.days || []).find((dd) => dd.date === btn.dataset.date);
        if (!day || !cell) return;
        const mine = (day.rows || []).filter((r) => tickers.has(String(r.ticker || "").toUpperCase()));
        cell.querySelectorAll(".cal-entry").forEach((e) => e.remove());
        btn.insertAdjacentHTML("beforebegin", mine.map((r) => calEntryHtml(r, names)).join(""));
        cell.querySelectorAll(".cal-entry").forEach((b) => b.addEventListener("click", () => getBriefing(b.dataset.ticker)));
        btn.remove();
      });
    });
  } catch { box.innerHTML = `<p class="meta">Calendar unavailable — try again later.</p>`; }
}
// Feature 11, Batch 67: the TipRanks-style week view — the
// default. A dark panel with five weekday columns (Mon–Fri);
// each day splits into Before open (☀) and After close (🌙),
// the timing itself is the structure, and every entry is a big
// logo tile with its ticker above it. Rows with no timing land
// in a "Time TBA" foot row, never guessed into a half.
// Saturday/Sunday reporters appear in a weekend strip below
// the grid, only when there are any. Clicking a tile runs the
// briefing. The Batch 66 month grid stays behind the Month
// toggle. "Most anticipated" is TipRanks' framing, not ours —
// the panel shows the directory companies reporting that
// week, with no ranking invented.
let calView = "week"; // "week" | "month"
let calWeek = null; // Monday "YYYY-MM-DD"; null = current week
function calViewToggleHtml() {
  return `<span class="cal-toggle"><button type="button" class="cal-view-btn${calView === "week" ? " is-on" : ""}" data-view="week">Week</button><button type="button" class="cal-view-btn${calView === "month" ? " is-on" : ""}" data-view="month">Month</button></span>`;
}
function wireCalViewToggle(box) {
  box.querySelectorAll(".cal-view-btn").forEach((btn) => {
    btn.addEventListener("click", () => { calView = btn.dataset.view; renderCalendar(); });
  });
}
function calWeekMonday(dateIso) {
  const d = dateIso ? new Date(`${dateIso}T00:00:00`) : new Date();
  const monday = new Date(d.getFullYear(), d.getMonth(), d.getDate() - ((d.getDay() + 6) % 7));
  return `${monday.getFullYear()}-${String(monday.getMonth() + 1).padStart(2, "0")}-${String(monday.getDate()).padStart(2, "0")}`;
}
function calWeekShift(weekIso, deltaWeeks) {
  const d = new Date(`${weekIso}T00:00:00`);
  const monday = new Date(d.getFullYear(), d.getMonth(), d.getDate() + deltaWeeks * 7);
  return `${monday.getFullYear()}-${String(monday.getMonth() + 1).padStart(2, "0")}-${String(monday.getDate()).padStart(2, "0")}`;
}
function calWeekTitle(mondayIso) {
  const mon = new Date(`${mondayIso}T00:00:00`);
  const fri = new Date(mon.getFullYear(), mon.getMonth(), mon.getDate() + 4);
  const fmt = (d) => d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  return `${fmt(mon)} – ${fmt(fri)}, ${fri.getFullYear()}`;
}
function calWeekTileHtml(r, names) {
  const t = String(r.ticker || "").toUpperCase();
  const name = esc(names[t] || r.name || t);
  return `<button type="button" class="wk-tile" data-ticker="${esc(t)}" title="${name} — click to run the briefing"><span class="wk-ticker">${esc(t)}</span><span class="wk-logo">${logoImg(t, "logo-img logo-wk")}</span></button>`;
}
function calWeekDayHtml(day, tickers, names, todayIso) {
  const d = new Date(`${day.date}T00:00:00`);
  const isToday = day.date === todayIso;
  const mine = (day.rows || []).filter((r) => tickers.has(String(r.ticker || "").toUpperCase()));
  const before = mine.filter((r) => r.time === "before");
  const after = mine.filter((r) => r.time === "after");
  const tba = mine.filter((r) => r.time !== "before" && r.time !== "after");
  const head = `${WEEKDAYS[d.getDay()]} ${d.toLocaleDateString("en-US", { month: "numeric", day: "numeric" })}`;
  if (day.error) return `<div class="wk-day${isToday ? " wk-today" : ""}"><div class="wk-day-head">${esc(head)}</div><span class="wk-err">Unavailable</span></div>`;
  return `<div class="wk-day${isToday ? " wk-today" : ""}"><div class="wk-day-head">${esc(head)}</div>` +
    `<div class="wk-halves"><div class="wk-half"><span class="wk-half-label" title="Reports before market open">☀</span>${before.map((r) => calWeekTileHtml(r, names)).join("")}</div>` +
    `<div class="wk-half"><span class="wk-half-label" title="Reports after market close">🌙</span>${after.map((r) => calWeekTileHtml(r, names)).join("")}</div></div>` +
    (tba.length ? `<div class="wk-tba"><span class="wk-tba-label">Time TBA</span>${tba.map((r) => calWeekTileHtml(r, names)).join("")}</div>` : "") +
    `</div>`;
}
function calWeekHtml(mondayIso, days, tickers, names, todayIso) {
  const byDate = {};
  for (const day of days || []) byDate[day.date] = day;
  const cols = [];
  for (let i = 0; i < 5; i++) {
    const d = new Date(`${mondayIso}T00:00:00`);
    const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate() + i).padStart(2, "0")}`;
    cols.push(calWeekDayHtml(byDate[iso] || { date: iso, rows: [] }, tickers, names, todayIso));
  }
  const weekend = [5, 6].map((i) => {
    const d = new Date(`${mondayIso}T00:00:00`);
    const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate() + i).padStart(2, "0")}`;
    return byDate[iso] || { date: iso, rows: [] };
  }).filter((day) => (day.rows || []).some((r) => tickers.has(String(r.ticker || "").toUpperCase())));
  const weekendHtml = weekend.length ? `<div class="wk-weekend">${weekend.map((day) => {
    const d = new Date(`${day.date}T00:00:00`);
    const mine = (day.rows || []).filter((r) => tickers.has(String(r.ticker || "").toUpperCase()));
    return `<span class="wk-weekend-day">${WEEKDAYS[d.getDay()]} ${d.getDate()}</span>` + mine.map((r) => calWeekTileHtml(r, names)).join("");
  }).join("")}</div>` : "";
  return `<div class="wk-panel"><div class="wk-nav"><button type="button" class="wk-nav-btn" data-shift="-1" aria-label="Previous week">‹</button><span class="wk-title">This week · ${calWeekTitle(mondayIso)}</span><button type="button" class="wk-nav-btn" data-shift="1" aria-label="Next week">›</button><button type="button" class="wk-today-btn">This week</button>${calViewToggleHtml()}</div>` +
    `<div class="wk-days">${cols.join("")}</div>${weekendHtml}</div>`;
}
async function renderCalendarWeek() {
  const box = $("calendar-grid");
  if (!box) return;
  const mondayIso = calWeek || calWeekMonday(null);
  box.innerHTML = `<p class="meta">Loading calendar…</p>`;
  try {
    const [resp, dir] = await Promise.all([
      fetch(`${ORCHESTRATOR_URL}/calendar?week=${mondayIso}`),
      loadDirectory(),
    ]);
    if (!resp.ok) throw new Error("calendar fetch failed");
    const data = await resp.json();
    const tickers = new Set((dir || []).map((c) => String(c.ticker || "").toUpperCase()));
    const names = {};
    for (const c of dir || []) names[String(c.ticker || "").toUpperCase()] = c.name || c.ticker;
    const today = new Date();
    const todayIso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
    box.innerHTML = calWeekHtml(data.week || mondayIso, data.days || [], tickers, names, todayIso);
    box.querySelectorAll(".wk-nav-btn").forEach((btn) => {
      btn.addEventListener("click", () => { calWeek = calWeekShift(calWeek || calWeekMonday(null), Number(btn.dataset.shift)); renderCalendarWeek(); });
    });
    box.querySelector(".wk-today-btn").addEventListener("click", () => { calWeek = null; renderCalendarWeek(); });
    wireCalViewToggle(box);
    box.querySelectorAll(".wk-tile").forEach((btn) => {
      btn.addEventListener("click", () => getBriefing(btn.dataset.ticker));
    });
  } catch { box.innerHTML = `<p class="meta">Calendar unavailable — try again later.</p>`; }
}
function renderCalendar() {
  if (calView === "month") renderCalendarGrid();
  else renderCalendarWeek();
}
renderCalendar();
// Batch 63: debounced, and never blocked by an in-flight AI search
// (the old `if (searching) return` froze suggestions for the whole
// AI round trip). Local filtering only — nothing here touches the
// network after the directory is cached.
let suggestTimer = null;
$("company-search").addEventListener("input", (e) => {
  const q = e.target.value.trim().toLowerCase();
  const box = $("company-results");
  if (q.length < 2) { show(box, false); return; }
  clearTimeout(suggestTimer);
  suggestTimer = setTimeout(async () => {
    const dir = await loadDirectory();
    // Guard against out-of-order resolves while the user keeps typing.
    if ($("company-search").value.trim().toLowerCase() !== q) return;
    const matches = localMatches(q, dir);
    if (!matches.length) { show(box, false); return; }
    renderSearchResults(matches, e.target.value.trim());
  }, 120);
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

// Feature 18: the third-company picker — the same directory
// matcher as the first picker, with picks going to startCompare3.
const addThirdBtn = $("compare-add-third");
if (addThirdBtn) addThirdBtn.addEventListener("click", () => {
  const picker = $("compare-third-picker");
  if (picker) show(picker, true);
  const search3 = $("compare-search-3");
  if (search3) search3.focus();
});
const search3El = $("compare-search-3");
if (search3El) search3El.addEventListener("input", async (e) => {
  const q = e.target.value.trim().toLowerCase();
  const box = $("compare-results-3");
  if (q.length < 2) { show(box, false); return; }
  const dir = await loadDirectory();
  if ($("compare-search-3").value.trim().toLowerCase() !== q) return;
  const matches = dir.filter((c) =>
    c.name.toLowerCase().includes(q) || c.ticker.toLowerCase().includes(q),
  ).slice(0, 5);
  if (!matches.length) { show(box, false); return; }
  renderCompareResults3(matches);
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
      `<button type="button" class="chip search-match" data-q="${esc(s.query)}">${s.ticker ? logoImg(s.ticker, "logo-img logo-chip") : ""}${esc(s.query)}${s.ticker ? ` <span class="tag tag-gray">${esc(s.ticker)}</span>` : ""}</button>`).join("");
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
    // Batch 59: a ranked volume list — rank, query, a bar sized to
    // the top query's count, and the count. The old "×N" chips
    // showed volume as text; the bar shows it at a glance.
    const max = Math.max(...top.map((t) => t.count));
    chips.innerHTML = top.map((t, i) =>
      `<button type="button" class="vol-row" data-q="${esc(t.query)}"><span class="vol-rank">${i + 1}</span><span class="vol-query">${esc(t.query)}</span><span class="vol-track"><span class="vol-bar" style="width: ${Math.max(6, Math.round((t.count / max) * 100))}%"></span></span><span class="vol-count">${t.count}</span></button>`).join("");
    chips.querySelectorAll(".vol-row").forEach((btn) => {
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
  const count = $("recent-briefings-count");
  if (!items.length) {
    // Batch 60: the card always shows — a fresh browser has no
    // cached briefings, and hiding the card left an empty third
    // column in the Discover grid. An empty state instead.
    chips.innerHTML = `<p class="disc-empty">No saved briefings yet — run one and it will appear here.</p>`;
    if (count) count.textContent = "0";
    show(wrap, true);
    return;
  }
  chips.innerHTML = items.map((it) =>
    `<button type="button" class="chip" data-t="${esc(it.ticker)}" data-q="${esc(it.quarter)}">${logoImg(it.ticker, "logo-img logo-chip")}${esc(it.ticker)}${it.label ? ` <span class="tag tag-gray">${esc(shortQuarterLabel(it.label))}</span>` : ""}</button>`).join("");
  if (count) count.textContent = String(items.length);
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
// Feature 17: the share link for a same-company compare carries
// &compareQuarter=<label> alongside ?ticker=<T>&compare=<T>.
// parseShareLink is a pure function so the round-trip is
// harness-testable. An invalid compareQuarter is dropped, never
// run as the latest quarter (getBriefing would turn a bad label
// into ""), so a bad link restores the base briefing only.
function parseShareLink(search) {
  const params = new URLSearchParams(search || "");
  const param = params.get("ticker");
  if (!param || !/^[A-Za-z]{1,10}$/.test(param.trim())) return null;
  const baseTicker = param.trim().toUpperCase();
  const out = { baseTicker, quarter: params.get("quarter") ? params.get("quarter").trim() : "", second: null, compareQuarter: null, third: null };
  const cParam = params.get("compare");
  if (cParam && /^[A-Za-z]{1,10}$/.test(cParam.trim())) {
    const second = cParam.trim().toUpperCase();
    if (second !== baseTicker) {
      out.second = second;
      // Feature 18: the third company — only when it differs
      // from both companies already in the comparison.
      const tParam = params.get("compare2");
      if (tParam && /^[A-Za-z]{1,10}$/.test(tParam.trim())) {
        const third = tParam.trim().toUpperCase();
        if (third !== baseTicker && third !== second) out.third = third;
      }
    } else {
      const cq = params.get("compareQuarter");
      if (cq && (/^Q[1-4] \d{4}$/.test(cq.trim()) || /^quarter ended \d{4}-\d{2}-\d{2}$/.test(cq.trim()))) {
        out.second = second;
        out.compareQuarter = cq.trim();
      }
    }
  }
  return out;
}
try {
  const parsed = parseShareLink(location.search);
  if (parsed) {
    const { baseTicker, quarter, second, compareQuarter, third } = parsed;
    $("company-search").value = baseTicker;
    if (second && !compareQuarter) {
      pendingAutoCompare = { second, base: baseTicker };
      if (third) pendingThirdCompare = third;
      const cs = $("compare-search");
      if (cs) cs.value = second;
    } else if (second && compareQuarter) {
      pendingAutoCompare = { second, base: baseTicker, compareQuarter };
    }
    // getBriefing validates the quarter itself (calendar "Qn YYYY"
    // and fiscal "quarter ended YYYY-MM-DD" both pass); the load
    // path must not pre-filter to calendar labels only, or a
    // shared fiscal link reloads as the latest quarter instead
    // of restoring its saved briefing (Batch 20 fix).
    getBriefing(baseTicker, quarter);
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
