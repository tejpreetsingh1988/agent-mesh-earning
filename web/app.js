// Frontend for the Agent Mesh earnings briefing.
// One POST to the Orchestrator Worker; everything rendered comes
// from the Briefing JSON it returns. No numbers are computed here.
//
// If the Workers were created under different project names, change
// this one URL — nothing else needs to change.
const ORCHESTRATOR_URL = "https://mesh-orchestrator-proof.tejpreetsingh1988.workers.dev";

// Live log: one line per pipeline step, streamed from the
// Orchestrator's SSE endpoint. If the stream itself fails before
// any event arrives (old edge cache, blocked stream, anything
// that keeps the first byte from coming back), fall back to the
// plain POST — the briefing is the same either way. If the
// stream dies AFTER events arrived, do not fall back: the run
// is already going server-side, and a second POST would start
// a duplicate run for the same ticker.
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
            return true;
          }
          if (ev.event === "error") {
            showBriefingError(ticker, ev.error || "Stream failed");
            return true;
          }
          const text = LOG_TEXT[ev.event];
          if (text) addLog(text(ev));
        }
      }
    }
  } catch (e) {
    // Stream broke mid-run: the run may still be going
    // server-side, so surface the failure, never a duplicate POST.
    if (sawEvent) {
      showBriefingError(ticker, `Live log stopped mid-run: ${e.message}`);
      return true;
    }
    return false;
  }
  // Stream ended without a briefing or an error event: if it
  // spoke at all, that is the outcome; otherwise fall back.
  if (sawEvent) {
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
  show($("skeleton"), true);
  show($("log"), true);
  logLines = [];
  $("log-list").innerHTML = "";
  $("log-now").textContent = "Now: starting…";
  try {
    let streamed;
    try {
      streamed = await runStream(ticker);
    } catch (e) {
      streamed = false;
    }
    if (!streamed) {
      try {
        await runPost(ticker);
      } catch (e) {
        showBriefingError(ticker, e.message);
      }
    }
  } finally {
    show($("skeleton"), false);
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
  // LLM stories use markdown bold for lead-ins. The page renders
  // plain text, so convert matched **bold** to <strong> (after
  // escaping, so this cannot inject markup) and drop any stray
  // markers instead of showing literal asterisks.
  $("b-story").innerHTML = String(b.story || "").split(/\n\n+/).map((p) => {
    const html = esc(p).replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>").replace(/\*\*/g, "");
    return `<p>${html}</p>`;
  }).join("");
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
