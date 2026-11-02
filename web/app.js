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
  return String(m || "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function round1(v) {
  return Number.isFinite(v) ? String(Math.round(v * 10) / 10) : "—";
}

function secs(ms) {
  if (!Number.isFinite(ms)) return "";
  return `${(ms / 1000).toFixed(1)}s`;
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
    return;
  }
  if (name === "scout_done") {
    const facts = ev.fact_list || [];
    const rows = facts.map((f) => {
      const src = (f.source && f.source.publisher) || "Source";
      return `<tr><td>${esc(prettyMetric(f.metric))}</td><td class="num">${round1(f.value)}</td>`
        + `<td>${esc(f.unit || "")}</td><td>${esc(f.period || "")}</td><td>${esc(src)}</td></tr>`;
    }).join("");
    setBody("scout",
      `<p class="agent-filing">${esc(ev.company_name || ticker)} — ${esc(ev.quarter_label || "")} — `
      + `${esc(ev.status || "")} · Transcript: ${esc(ev.transcript_status || "unknown")}</p>`
      + `<div class="table-wrap"><table><thead><tr><th>Fact</th><th class="num">Value</th>`
      + `<th>Unit</th><th>Period</th><th>Source</th></tr></thead><tbody>${rows}</tbody></table></div>`);
    setStatus("scout", "done", ev.duration_ms ? `took ${secs(ev.duration_ms)}` : "");
    setConductor("Conductor — Pipeline Lead", "Scout done. Analyst is computing.");
    setStatus("analyst", "working", "");
    workingAgent = "analyst";
    return;
  }
  if (name === "analyst_done") {
    analystRuns += 1;
    const claims = ev.claim_list || [];
    const rows = claims.map((c) => `<tr><td>${esc(c.text || "")}</td>`
      + `<td class="num">${round1(c.value)}</td><td>${esc(c.derivation || "")}</td></tr>`).join("");
    const note = analystRuns > 1
      ? `<p class="agent-note">Revised after Critic feedback.</p>` : "";
    setBody("analyst", note
      + `<div class="table-wrap"><table><thead><tr><th>Claim</th><th class="num">Value</th>`
      + `<th>Derivation</th></tr></thead><tbody>${rows}</tbody></table></div>`);
    setStatus("analyst", "done", ev.duration_ms ? `took ${secs(ev.duration_ms)}` : "");
    setConductor("Conductor — Pipeline Lead", "Analyst done. Critic is re-checking.");
    setStatus("critic", "working", "");
    workingAgent = "critic";
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
    } else {
      setBody("critic",
        `<p class="agent-fail">Attempt ${ev.attempt} — FAIL. Analyst is revising.</p>`
        + `<ul class="list">${issues.map((i) => `<li>${esc(issueText(i))}</li>`).join("")}</ul>`);
      setStatus("critic", "revising", "");
      setStatus("analyst", "working", "");
      workingAgent = "analyst";
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

async function getBriefing() {
  const ticker = $("ticker").value.trim().toUpperCase();
  if (!ticker || running) return;
  running = true;
  $("ticker").value = ticker;
  $("go").disabled = true;
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
    $("go").disabled = false;
    running = false;
  }
}

$("log-download").addEventListener("click", () => {
  if (!logLines.length) return;
  const blob = new Blob([logLines.join("\n") + "\n"], { type: "text/plain" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `briefing-${$("ticker").value.trim().toUpperCase()}-log.txt`;
  a.click();
  URL.revokeObjectURL(a.href);
});

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
    return `<tr><td>${esc(row.claim)}</td><td class="num">${value}</td><td>${esc(derivation)}</td></tr>`;
  }).join("");
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

$("go").addEventListener("click", getBriefing);
$("ticker").addEventListener("keydown", (e) => {
  if (e.key === "Enter") getBriefing();
});
document.querySelectorAll(".chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    $("ticker").value = chip.dataset.ticker;
    getBriefing();
  });
});
