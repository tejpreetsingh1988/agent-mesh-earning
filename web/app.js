// Frontend for the Agent Mesh earnings briefing.
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
  const order = ["total_revenue", "operating_income", "gaap_eps"];
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
const analystExpanded = {};

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
    derivation: String(c.derivation || "").replace(/, from facts.*$/, "") };
}

function analystTableHtml(key, claims) {
  const st = analystTableState[key] || (analystTableState[key] = { filter: "all", sort: "original" });
  const expanded = analystExpanded[key] || (analystExpanded[key] = new Set());
  const parsed = (claims || []).map((c, i) => ({ ...parseClaim(c), _i: i }));
  const filtered = parsed.filter((p) => st.filter === "all" || p.kind === st.filter);
  const sorted = [...filtered];
  if (st.sort === "abs") sorted.sort((a, b) => Math.abs(b.valueNum || 0) - Math.abs(a.valueNum || 0));
  else if (st.sort === "metric") sorted.sort((a, b) => a.metric.localeCompare(b.metric));
  else sorted.sort((a, b) => a._i - b._i);
  const filters = [["all", "All"], ["growth", "Growth"], ["margin", "Margin"], ["eps", "EPS / consensus"], ["price", "Price"], ["other", "Other"]];
  const kindColor = { growth: "#1d4ed8", margin: "#6d28d9", eps: "#b45309", price: "#0f766e", other: "#71717a" };
  if (!parsed.length) return `<p class="agent-waiting">No claims returned.</p>`;
  const rows = sorted.map((p) => {
    const isOpen = expanded.has(p._i);
    const main = `<tr data-idx="${p._i}" title="Click to ${isOpen ? "hide" : "show"} its formula">`
      + `<td class="metric-cell"><span class="kind-dot" style="background:${kindColor[p.kind] || "#71717a"}"></span>${esc(p.metric)}</td>`
      + `<td class="period-cell">${esc(p.period)}</td>`
      + `<td class="result-cell"><span class="result-pill kind-${p.kind}${(p.valueNum || 0) < 0 ? " negative" : ""}">${esc(p.value)}${p.arrow}</span></td>`
      + `<td class="detail-cell">${esc(p.detail)}</td></tr>`;
    const formula = `<tr class="formula-row" data-formula-for="${p._i}"${isOpen ? "" : " hidden"}>`
      + `<td colspan="4"><code>${esc(p.derivation || "No derivation supplied by the Analyst.")}</code></td></tr>`;
    return main + formula;
  }).join("");
  return `<div class="analyst-controls" data-controls="${key}">`
    + filters.map(([f, label]) => `<button type="button" class="analyst-filter${st.filter === f ? " is-on" : ""}" data-filter="${f}">${label}</button>`).join("")
    + `<select class="analyst-sort" aria-label="Sort claims">`
    + `<option value="original"${st.sort === "original" ? " selected" : ""}>Original order</option>`
    + `<option value="abs"${st.sort === "abs" ? " selected" : ""}>Biggest % first</option>`
    + `<option value="metric"${st.sort === "metric" ? " selected" : ""}>Metric A–Z</option></select></div>`
    + `<div class="analyst-table-wrap"><table class="analyst-table"><thead><tr>`
    + `<th>Metric</th><th>Period</th><th class="num">Result</th><th>Detail</th></tr></thead>`
    + `<tbody>${rows}</tbody></table></div>`
    + `<p class="analyst-note">Click a row to show its exact formula. Filters and sorting only reorder the Analyst&rsquo;s claims.</p>`;
}

function renderAnalyst(key, claims, el, noteHtml) {
  analystTableData[key] = claims || [];
  if (!el) return;
  el.innerHTML = (noteHtml || "") + analystTableHtml(key, analystTableData[key]);
  const controls = el.querySelector(`[data-controls="${key}"]`);
  if (controls) {
    controls.querySelectorAll("[data-filter]").forEach((btn) => {
      btn.addEventListener("click", () => {
        analystTableState[key].filter = btn.dataset.filter;
        renderAnalyst(key, analystTableData[key], el, noteHtml);
      });
    });
    const sel = controls.querySelector(".analyst-sort");
    if (sel) sel.addEventListener("change", () => {
      analystTableState[key].sort = sel.value;
      renderAnalyst(key, analystTableData[key], el, noteHtml);
    });
  }
  el.querySelectorAll("tbody tr[data-idx]").forEach((row) => {
    row.addEventListener("click", () => {
      const idx = Number(row.dataset.idx);
      const set = analystExpanded[key] || (analystExpanded[key] = new Set());
      if (set.has(idx)) set.delete(idx); else set.add(idx);
      const fr = el.querySelector(`[data-formula-for="${idx}"]`);
      if (fr) fr.hidden = !set.has(idx);
      row.title = `Click to ${set.has(idx) ? "hide" : "show"} its formula`;
    });
  });
}

// ---- Charts + glance + handover loop (right/left rails) ----
// All chart data comes from streamed Scout facts / Analyst claims
// stored below. Nothing is invented here: a chart with no source
// data stays empty with its placeholder text.
let lastScoutFacts = [];
let lastAnalystClaims = [];
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
function updateTrendChart() {
  const tables = pivotFacts(lastScoutFacts);
  const rev = tables.find((t) => t.metric === "total_revenue");
  if (!rev || !rev.periods.length) { destroyChart("trend"); setChartEmpty("trend", true); return; }
  const labels = rev.periods.map(quarterLabel);
  const data = rev.cells.map((c) => Number.isFinite(c.value) ? c.value : null);
  setChartEmpty("trend", false);
  makeChart("trend", "bar", labels, [{ label: `Revenue (${rev.unit || ""})`.trim(), data,
    backgroundColor: labels.map((_, i) => i === labels.length - 1 ? "#1d4ed8" : "#93c5fd"),
    borderRadius: 6 }]);
}
function updateGrowthChart() {
  const rows = (lastAnalystClaims || []).map(parseClaim)
    .filter((p) => /yoy/i.test(p.metric) && p.kind !== "other" && p.valueNum !== null);
  if (!rows.length) { destroyChart("growth"); setChartEmpty("growth", true); return; }
  setChartEmpty("growth", false);
  const colors = { growth: "#1d4ed8", margin: "#6d28d9", eps: "#b45309", price: "#0f766e", other: "#71717a" };
  makeChart("growth", "bar", rows.map((r) => r.metric.replace(/\s*YoY\s*/i, "")),
    [{ label: "YoY %", data: rows.map((r) => r.valueNum),
      backgroundColor: rows.map((r) => colors[r.kind] || "#71717a"), borderRadius: 6 }]);
}
function updateEpsAndMarginCharts() {
  const parsed = (lastAnalystClaims || []).map(parseClaim);
  const epsClaim = parsed.find((p) => /consensus/i.test(p.metric));
  if (epsClaim) {
    const m = epsClaim.detail.match(/([\d.]+)\s*vs\s*([\d.]+)/);
    if (m) {
      setChartEmpty("eps", false);
      makeChart("eps", "bar", ["Reported", "Forecast"],
        [{ label: "EPS ($)", data: [Number(m[1]), Number(m[2])],
          backgroundColor: ["#b45309", "#fde68a"], borderRadius: 6 }]);
    }
  } else { destroyChart("eps"); setChartEmpty("eps", true); }
  const margin = parsed.find((p) => p.kind === "margin");
  if (margin && margin.valueNum !== null) {
    setChartEmpty("margin", false);
    makeChart("margin", "doughnut", ["Operating margin", "Rest"],
      [{ data: [margin.valueNum, Math.max(0, 100 - margin.valueNum)],
        backgroundColor: ["#6d28d9", "#e4e4e7"], borderWidth: 0 }]);
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
}
function clearCharts() {
  ["trend", "growth", "eps", "margin"].forEach((id) => { destroyChart(id); setChartEmpty(id, true); });
  lastScoutFacts = []; lastAnalystClaims = [];
  ["glance-quarter", "glance-revenue", "glance-margin", "glance-eps"].forEach((id) => { const el = $(id); if (el) el.textContent = "—"; });
}

const LOOP_ORDER = ["scout", "analyst", "critic", "writer", "conductor"];
const LOOP_LABEL = { scout: "Scout", analyst: "Analyst", critic: "Critic", writer: "Writer", conductor: "Conductor" };
function setLoop(agent, statusText) {
  LOOP_ORDER.forEach((a) => {
    const node = $(`loop-node-${a}`);
    if (!node) return;
    node.classList.toggle("is-active", a === agent);
    node.classList.toggle("is-done", agent ? LOOP_ORDER.indexOf(a) < LOOP_ORDER.indexOf(agent) : false);
  });
  const center = $("loop-center"), sub = $("loop-center-sub"), status = $("loop-status");
  if (center) center.textContent = agent ? LOOP_LABEL[agent] : "Idle";
  if (sub) sub.textContent = agent ? "has the baton" : "Pick a company";
  if (status) status.textContent = statusText || (agent ? `${LOOP_LABEL[agent]} is working.` : "No run yet. The loop idles until a briefing starts.");
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
        color: { value: ["#0f766e", "#1d4ed8", "#6d28d9", "#db2777", "#b45309"] },
        links: { enable: true, color: "#cbd5e1", distance: 140, opacity: 0.5 },
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
    setStatus(a, "waiting", "");
    const waiting = {
      scout: "Waiting for the pipeline to reach Scout.",
      analyst: "Waiting for Scout\u2019s facts.",
      critic: "Waiting for Analyst\u2019s claims.",
      writer: "Waiting for Critic\u2019s pass.",
    }[a];
    setBody(a, `<p class="agent-waiting">${waiting}</p>`);
  });
  analystRuns = 0;
  workingAgent = null;
  const feed = $("handover-feed");
  if (feed) feed.innerHTML = "";
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
  if (name === "scout_started") {
    setConductor("Conductor — Pipeline Lead", `Scout is fetching filings for ${ticker}.`);
    setStatus("scout", "working", "");
    workingAgent = "scout";
    setLoop("scout", "Scout is fetching filings.");
    addHandover("Conductor → Scout: fetch filings");
    return;
  }
  if (name === "scout_done") {
    const facts = ev.fact_list || [];
    lastScoutFacts = facts;
    updateTrendChart();
    const publishers = [...new Set(facts.map((f) => (f.source && f.source.publisher) || "").filter(Boolean))];
    setBody("scout",
      `<p class="agent-filing">${esc(ev.company_name || ticker)} — ${esc(ev.quarter_label || "")} — `
      + `${esc(ev.status || "")} · Transcript: ${esc(ev.transcript_status || "unknown")}</p>`
      + pivotTablesHtml(facts)
      + (publishers.length ? `<p class="metric-footnote">Sources: ${esc(publishers.join(", "))}.</p>` : ""));
    setStatus("scout", "done", ev.duration_ms ? `took ${secs(ev.duration_ms)}` : "");
    setConductor("Conductor — Pipeline Lead", "Scout done. Analyst is computing.");
    setStatus("analyst", "working", "");
    workingAgent = "analyst";
    setLoop("analyst", `Scout handed over ${facts.length} facts.`);
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
    renderAnalyst("analyst", claims, analystEl, note);
    updateAllCharts();
    setStatus("analyst", "done", ev.duration_ms ? `took ${secs(ev.duration_ms)}` : "");
    setConductor("Conductor — Pipeline Lead", "Analyst done. Critic is re-checking.");
    setStatus("critic", "working", "");
    workingAgent = "critic";
    setLoop("critic", `Analyst handed over ${claims.length} claims.`);
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
      setConductor("Conductor — Pipeline Lead", "Critic passed. Writer is writing.");
      setStatus("writer", "working", "");
      workingAgent = "writer";
      setLoop("writer", "Critic passed — Writer has the baton.");
      addHandover("Critic → Writer: PASS");
    } else {
      setBody("critic",
        `<p class="agent-fail">Attempt ${ev.attempt} — FAIL. Analyst is revising.</p>`
        + `<ul class="list">${issues.map((i) => `<li>${esc(issueText(i))}</li>`).join("")}</ul>`);
      setStatus("critic", "revising", "");
      setStatus("analyst", "working", "");
      workingAgent = "analyst";
      setLoop("analyst", "Critic failed the claims — Analyst is revising.");
      addHandover("Critic → Analyst: FAIL, revising");
    }
    return;
  }
  if (name === "writer_done") {
    setBody("writer",
      `<div class="story">${storyHtml(ev.story || "")}</div>`
      + `<p class="meta">Story written via: ${esc(ev.story_model || "—")}</p>`);
    setStatus("writer", "done", ev.duration_ms ? `took ${secs(ev.duration_ms)}` : "");
    setConductor("Conductor — Pipeline Lead", "Writer done. Assembling the briefing.");
    workingAgent = null;
    setLoop("conductor", "Writer handed the story back to the Conductor.");
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

function showBriefingError(ticker, message) {
  $("error-msg").textContent = `Could not build a briefing for ${ticker}.\n${message}\n\n`
    + `If this says Critic FAIL, the agents disagreed about a number and refused to publish — `
    + `that refusal is the product working. If it says NOT_REPORTED_YET, the company has not `
    + `reported its most recent quarter yet. Otherwise, try again in a minute.`;
  show($("error"), true);
}

// Returns true when the stream spoke (briefing rendered or an
// error event shown) and false when it failed before any event,
// which is the only case that falls back to POST.
async function runStream(ticker) {
  const resp = await fetch(`${ORCHESTRATOR_URL}/tasks/stream?ticker=${encodeURIComponent(ticker)}`);
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
            render(ev.briefing);
            const total = ((Date.now() - runStartedAt) / 1000).toFixed(1);
            stopElapsed(`Done in ${total}s`);
            setConductor("Conductor — Pipeline Lead", `Briefing complete in ${total}s.`);
            setLoop("conductor", `Briefing complete in ${total}s.`);
            addHandover("Conductor: briefing complete");
            return true;
          }
          if (ev.event === "error") {
            if (workingAgent) setStatus(workingAgent, "failed", "");
            stopElapsed();
            setConductor("Conductor — Pipeline Lead", "Pipeline stopped with an error.");
            showBriefingError(ticker, ev.error || "Stream failed");
            return true;
          }
          onStreamEvent(ev, ticker);
          const text = LOG_TEXT[ev.event];
          if (text) addLog(text(ev));
        }
      }
    }
  } catch (e) {
    // Stream broke mid-run: the run may still be going
    // server-side, so surface the failure, never a duplicate POST.
    if (sawEvent) {
      if (workingAgent) setStatus(workingAgent, "failed", "");
      stopElapsed();
      setConductor("Conductor — Pipeline Lead", "Live stream stopped mid-run.");
      showBriefingError(ticker, `Live log stopped mid-run: ${e.message}`);
      return true;
    }
    return false;
  }
  // Stream ended without a briefing or an error event: if it
  // spoke at all, that is the outcome; otherwise fall back.
  if (sawEvent) {
    stopElapsed();
    showBriefingError(ticker, "Live log ended before the briefing arrived");
    return true;
  }
  return false;
}

async function runPost(ticker) {
  const resp = await fetch(`${ORCHESTRATOR_URL}/tasks/send`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ticker }),
  });
  const body = await resp.json();
  if (!resp.ok || body.state !== "completed") {
    throw new Error(body.error || body.result || `Request failed (HTTP ${resp.status})`);
  }
  render(body.result);
}

// The ticker box is gone (Nov 2, 2026): the company search is
// the only search. The briefing's ticker lives here, set by the
// suggestion click that starts the run.
let currentTicker = "";

async function getBriefing(ticker) {
  ticker = String(ticker || "").trim().toUpperCase();
  if (!ticker || running) return;
  // Shareable link: the URL always names the briefing being run.
  try {
    const url = new URL(location.href);
    url.searchParams.set("ticker", ticker);
    history.replaceState(null, "", url);
  } catch { /* URL sharing is best-effort */ }
  currentTicker = ticker;
  running = true;
  $("company-go").disabled = true;
  show($("briefing"), false);
  show($("error"), false);
  show($("agents"), true);
  show($("log"), true);
  resetCards();
  logLines = [];
  $("log-list").innerHTML = "";
  $("log-now").textContent = "Now: starting…";
  setConductor("Conductor — Pipeline Lead", "Starting the pipeline.");
  startElapsed();
  try {
    let streamed;
    try {
      streamed = await runStream(ticker);
    } catch (e) {
      streamed = false;
    }
    if (!streamed) {
      setConductor("Conductor — Pipeline Lead",
        "Live stream did not speak; showing the final briefing only.");
      try {
        await runPost(ticker);
        stopElapsed();
      } catch (e) {
        stopElapsed();
        showBriefingError(ticker, e.message);
      }
    }
  } finally {
    stopElapsed($("conductor-time").textContent || undefined);
    $("company-go").disabled = false;
    running = false;
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

function render(b) {
  $("b-ticker").textContent = b.ticker;
  $("b-quarter").textContent = b.quarter_label;
  $("b-verdict").textContent = b.verdict;
  // Claim values are percentages; the raw float (8.868501529051978)
  // is an internal artifact, so round to the one decimal the claim
  // text itself uses. Derivations drop their "from facts …" suffix:
  // the internal fact IDs are not something a reader can use.
  // Same claim blocks as the Analyst card, so the record matches
  // what the card showed.
  const briefingClaims = (b.table || []).map((row) => ({
    text: row.claim, value: row.value,
    derivation: String(row.derivation || "").replace(/, from facts.*$/, ""),
  }));
  lastAnalystClaims = briefingClaims;
  renderAnalyst("briefing", briefingClaims, $("b-table"), "");
  updateAllCharts(b.quarter_label);
  const drivers = b.drivers || [];
  show($("sec-drivers"), drivers.length > 0);
  $("b-drivers").innerHTML = drivers.map((d) => `<li>${esc(d)}</li>`).join("");
  show($("sec-market"), Boolean(b.market_reaction));
  $("b-reaction").textContent = b.market_reaction || "";
  $("b-story").innerHTML = storyHtml(b.story || "");
  $("b-model").textContent = b.story_model || "—";
  $("b-sources").innerHTML = (b.sources || []).map((s) => {
    const label = esc(s.publisher || "Source");
    return s.url ? `<li><a href="${esc(s.url)}" target="_blank" rel="noopener">${label}</a></li>`
                 : `<li>${label}</li>`;
  }).join("");
  $("b-trace").textContent = b.trace_id || "—";
  // The Analyst copies pack.missing into risks, so tool notes (the
  // absent price feed, in the cloud build) arrive inside
  // guidance_and_watch. They are honest data notes, not guidance,
  // so show them under their own heading instead of hiding them.
  const isNote = (w) => /No module named|failed:/.test(w);
  const watch = (b.guidance_and_watch || []).filter((w) => !isNote(w));
  const notes = (b.guidance_and_watch || []).filter(isNote);
  show($("sec-watch"), watch.length > 0);
  $("b-watch").innerHTML = watch.map((w) => `<li>${esc(w)}</li>`).join("");
  show($("sec-notes"), notes.length > 0);
  $("b-notes").innerHTML = notes.map((w) => `<li>${esc(w)}</li>`).join("");
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

function renderSearchResults(matches, query) {
  const box = $("company-results");
  if (!matches.length) {
    box.innerHTML = `<p class="search-empty">No company matched "${esc(query)}" — try a different spelling, `
      + `or a ticker like GOOGL (each company page carries its ticker).</p>`;
  } else {
    box.innerHTML = matches.map((m) =>
      `<button type="button" class="chip search-match" data-ticker="${esc(m.ticker)}">`
      + `${esc(m.name)} (${esc(m.ticker)})</button>`).join("");
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
    renderSearchResults(searchCache.get(query), query);
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
    searchCache.set(query, matches);
    renderSearchResults(matches, query);
  } catch (e) {
    box.innerHTML = `<p class="search-empty">Company search is unavailable right now (${esc(e.message)}) — use the ticker box below.</p>`;
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

// Shareable briefing links: ?ticker=INTC runs that briefing on load.
try {
  const param = new URLSearchParams(location.search).get("ticker");
  if (param && /^[A-Za-z]{1,10}$/.test(param.trim())) {
    $("company-search").value = param.trim().toUpperCase();
    getBriefing(param.trim().toUpperCase());
  }
} catch { /* a bad share link never breaks the page */ }

// Loop legend + nodes: jump to that agent's card. Background last,
// so a CDN failure can never block search or the briefing.
document.querySelectorAll(".loop-leg").forEach((btn) => {
  btn.addEventListener("click", () => {
    const target = $(`card-${btn.dataset.jump}`);
    if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
  });
});
document.querySelectorAll(".loop-node").forEach((node) => {
  node.addEventListener("click", () => {
    const agent = node.dataset.agent;
    const target = agent === "conductor" ? $("agents") : $(`card-${agent}`);
    if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
  });
});
initBackground();
