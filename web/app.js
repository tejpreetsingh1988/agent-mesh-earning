// Frontend for the Agent Mesh earnings briefing.
// One POST to the Orchestrator Worker; everything rendered comes
// from the Briefing JSON it returns. No numbers are computed here.
//
// If the Workers were created under different project names, change
// this one URL — nothing else needs to change.
const ORCHESTRATOR_URL = "https://mesh-orchestrator-proof.tejpreetsingh1988.workers.dev";

const STAGES = [
  "Scout is collecting evidence from filings and consensus…",
  "Analyst is computing the claims…",
  "Critic is independently re-checking every number…",
  "Writer is drafting the story (this is the slow step)…",
];

const $ = (id) => document.getElementById(id);

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function show(el, on) { el.hidden = !on; }

async function getBriefing() {
  const ticker = $("ticker").value.trim().toUpperCase();
  if (!ticker) return;
  $("go").disabled = true;
  show($("briefing"), false);
  show($("error"), false);
  const status = $("status");
  show(status, true);
  const started = Date.now();
  let stage = 0;
  status.textContent = STAGES[0];
  const timer = setInterval(() => {
    stage = Math.min(stage + 1, STAGES.length - 1);
    const secs = Math.round((Date.now() - started) / 1000);
    status.textContent = `${STAGES[stage]} (${secs}s so far)`;
  }, 20000);
  try {
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
  } catch (e) {
    const err = $("error");
    err.textContent = `Could not build a briefing for ${esc(ticker)}.\n${e.message}\n\n`
      + `If this says Critic FAIL, the agents disagreed about a number and refused to publish — `
      + `that refusal is the product working. If it says NOT_REPORTED_YET, the company has not `
      + `reported its most recent quarter yet. Otherwise, try again in a minute.`;
    show(err, true);
  } finally {
    clearInterval(timer);
    show(status, false);
    $("go").disabled = false;
  }
}

function render(b) {
  $("b-ticker").textContent = b.ticker;
  $("b-quarter").textContent = b.quarter_label;
  $("b-verdict").textContent = b.verdict;
  $("b-table").innerHTML = (b.table || []).map((row) => {
    const value = row.value === null || row.value === undefined ? "—" : esc(row.value);
    return `<tr><td>${esc(row.claim)}</td><td>${value}</td><td>${esc(row.derivation)}</td></tr>`;
  }).join("");
  $("b-drivers").innerHTML = (b.drivers || []).map((d) => `<li>${esc(d)}</li>`).join("");
  $("b-reaction").textContent = b.market_reaction || "No price-reaction claim in this briefing.";
  $("b-watch").innerHTML = (b.guidance_and_watch || []).map((w) => `<li>${esc(w)}</li>`).join("");
  $("b-story").innerHTML = String(b.story || "").split(/\n\n+/).map((p) => `<p>${esc(p)}</p>`).join("");
  $("b-model").textContent = b.story_model || "—";
  $("b-sources").innerHTML = (b.sources || []).map((s) => {
    const label = esc(s.publisher || "Source");
    return s.url ? `<li><a href="${esc(s.url)}" target="_blank" rel="noopener">${label}</a></li>`
                 : `<li>${label}</li>`;
  }).join("");
  $("b-trace").textContent = b.trace_id || "—";
  show($("briefing"), true);
}

$("go").addEventListener("click", getBriefing);
$("ticker").addEventListener("keydown", (e) => {
  if (e.key === "Enter") getBriefing();
});
