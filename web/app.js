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
    // Claim values are percentages; the raw float (8.868501529051978)
    // is an internal artifact, so round to the one decimal the claim
    // text itself uses. Derivations drop their "from facts …" suffix:
    // the internal fact IDs are not something a reader can use.
    const value = Number.isFinite(row.value) ? String(Math.round(row.value * 10) / 10) : "—";
    const derivation = String(row.derivation || "").replace(/, from facts.*$/, "");
    return `<tr><td>${esc(row.claim)}</td><td>${value}</td><td>${esc(derivation)}</td></tr>`;
  }).join("");
  const drivers = b.drivers || [];
  show($("h-drivers"), drivers.length > 0);
  show($("b-drivers"), drivers.length > 0);
  $("b-drivers").innerHTML = drivers.map((d) => `<li>${esc(d)}</li>`).join("");
  $("b-reaction").textContent = b.market_reaction
    || "Not available in the cloud briefing — the Workers don't bundle a price feed, so this briefing covers filings, consensus, and the call only.";
  // The Analyst copies pack.missing into risks, so tool notes (the
  // absent price feed, in the cloud build) arrive inside
  // guidance_and_watch. They are honest data notes, not guidance,
  // so show them under their own heading instead of hiding them.
  const isNote = (w) => /No module named|failed:/.test(w);
  const watch = (b.guidance_and_watch || []).filter((w) => !isNote(w));
  const notes = (b.guidance_and_watch || []).filter(isNote);
  show($("h-watch"), watch.length > 0);
  show($("b-watch"), watch.length > 0);
  $("b-watch").innerHTML = watch.map((w) => `<li>${esc(w)}</li>`).join("");
  show($("sec-notes"), notes.length > 0);
  $("b-notes").innerHTML = notes.map((w) => `<li>${esc(w)}</li>`).join("");
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
