"""Streaming briefing — the activity log, as events.

stream_briefing(ticker, mcp_call) yields (event, briefing_or_None)
tuples in real time. The briefing runs in a worker thread; the
Tracer puts every event (including MCP calls made inside Scout and
Critic) onto a queue, and the generator yields them as they arrive.
That is what makes the log live rather than a burst at the end:
an MCP event is yielded when that call actually happens, not after
Scout finishes.

The last tuple is always (briefing_done_event, Briefing) or, on
failure, the error event has already been yielded and no briefing
follows. The LLM, when configured, appears only in Writer, for
story prose validated against the verified claims and transcript;
Analyst stays deterministic. The stream emits an explicit llm_note
for the Writer step in either case — model + tokens + latency when
a model was used, or "deterministic story" when it was not — so
model activity is never faked.
"""
import queue
import threading
import uuid

from .analyst import analyse
from .critic import critique
from .mcp_client import make_traced_client
from .schemas import Analysis, Briefing, EvidencePack
from .scout import collect_evidence
from .trace import Tracer
from .writer import write_briefing


def _run(t: str, mcp_call, tr: Tracer):
    """Run the pipeline synchronously, emitting trace events.
    Returns a Briefing, or None if the pipeline failed (the error
    event has already been emitted)."""
    tr.emit("Orchestrator", "request", "INFO", f"Briefing requested for {t}",
            "Pipeline: Scout -> Analyst -> Critic (gate) -> Writer. No briefing is published if Critic fails.")
    traced = make_traced_client(tr, "Scout", inner=mcp_call)

    tr.emit("Scout", "stage_start", "RUNNING", "Scout gathering evidence",
            "Filings, quarterly history, price closes, and consensus — evidence only, no interpretation yet.")
    try:
        pack = collect_evidence(t, traced)
    except Exception as e:
        tr.emit("Scout", "error", "FAIL", "Scout failed", str(e)[:300])
        tr.emit("Orchestrator", "error", "FAIL", "Briefing failed at Scout", str(e)[:300])
        return None
    if pack.status != "REPORTED":
        tr.emit("Scout", "stage_done", "WARN", "Scout finished: no reported quarter found",
                f"Missing: {'; '.join(pack.missing)[:300]}")
        tr.emit("Orchestrator", "error", "FAIL", f"No briefing for {t}: NOT_REPORTED_YET",
                "; ".join(pack.missing)[:300])
        return None
    tr.emit("Scout", "stage_done", "DONE", f"Scout finished: {pack.quarter_label}, {len(pack.facts)} facts",
            f"Quarter end {pack.quarter_end}, filed {pack.report_date.date()}. Missing: {len(pack.missing)} notes.")
    for note in pack.missing:
        tr.emit("Scout", "warn", "WARN", "Scout note", note)

    tr.emit("Orchestrator", "handoff", "HANDOFF", "Passing EvidencePack to Analyst",
            f"{len(pack.facts)} facts, consensus status {(pack.consensus or {}).get('status', 'none')}.")
    tr.emit("Analyst", "stage_start", "RUNNING", "Analyst computing from the EvidencePack only",
            "YoY (12-month pairs), QoQ (3-month pairs), margin, beat/miss per basis — no live data calls in this stage.")
    tr.emit("Analyst", "llm_note", "INFO", "Model step: none for analysis",
            "Analyst is deterministic code over tool outputs, not a model call — by design, so no "
            "number can be hallucinated. The LLM is used only later, in Writer, for story prose "
            "over these verified claims.")
    analysis = analyse(pack)
    tr.emit("Analyst", "stage_done", "DONE", f"Analyst finished: {len(analysis.claims)} claims, {len(analysis.beat_miss)} beat/miss entries",
            analysis.verdict_draft)

    tr.emit("Orchestrator", "handoff", "HANDOFF", "Passing EvidencePack + Analysis to Critic",
            "Critic does not trust Analyst — it re-queries MCP and recomputes every claim.")
    tr.emit("Critic", "stage_start", "RUNNING", "Critic independently re-checking",
            "Re-querying filings and consensus, recomputing YoY/QoQ/margin/beat-miss, checking evidence existence and EPS basis labels.")
    traced_critic = make_traced_client(tr, "Critic", inner=mcp_call)
    attempts = 0
    crit = None
    while attempts < 2:
        attempts += 1
        crit = critique(pack, analysis, mcp_call=traced_critic)
        tr.emit("Critic", "critic_verdict", "DONE" if crit.verdict == "PASS" else "FAIL",
                f"Critic verdict (attempt {attempts}/2): {crit.verdict}",
                f"Issues: {len(crit.issues)}. Rechecked: {'; '.join(crit.rechecked_facts) or 'none'}.")
        if crit.verdict == "PASS":
            break
        if attempts < 2:
            tr.emit("Orchestrator", "retry", "RETRY", "Critic failed — re-running Analyst once, then re-checking",
                    f"Issues: {'; '.join(i.get('message', '') for i in crit.issues)[:300]}")
            analysis = analyse(pack)
    if crit is None or crit.verdict != "PASS":
        tr.emit("Orchestrator", "error", "FAIL", "No briefing published: Critic failed",
                f"Issues: {'; '.join(i.get('message', '') for i in (crit.issues if crit else []))[:500]}")
        return None

    tr.emit("Orchestrator", "handoff", "HANDOFF", "Critic passed — passing approved Analysis to Writer",
            "Writer may only use the approved Analysis and the EvidencePack's sources.")
    tr.emit("Writer", "stage_start", "RUNNING", "Writer writing the final briefing",
            "Claims copied verbatim from the approved Analysis; the story section is LLM prose "
            "only if an OpenRouter key is configured, validated against the claims and transcript, "
            "otherwise a deterministic story.")
    briefing = write_briefing(pack, analysis, str(uuid.uuid4()))
    if briefing.story_model.startswith("deterministic"):
        tr.emit("Writer", "llm_note", "INFO", "Model step: deterministic story used",
                briefing.story_model)
    else:
        tr.emit("Writer", "llm_note", "INFO", f"Model call: {briefing.story_model}",
                f"Tokens in {briefing.story_tokens_in}, out {briefing.story_tokens_out}, "
                f"latency {briefing.story_latency_s}s. Story was validated against verified "
                "claims and the transcript before publication.")
    tr.emit("Writer", "stage_done", "DONE", "Writer finished",
            f"{len(briefing.table)} table rows, {len(briefing.drivers)} drivers, {len(briefing.sources)} sources, "
            f"story via {briefing.story_model}.")
    sources_detail = "; ".join(f"{s.publisher}" for s in briefing.sources)
    tr.emit("Orchestrator", "summary", "DONE", "Processed: briefing complete",
            f"Facts {len(pack.facts)}, claims {len(analysis.claims)}, Critic PASS, sources: {sources_detail}.")
    return briefing


def stream_briefing(ticker: str, mcp_call=None, tracer: Tracer | None = None):
    """Yield (event, briefing_or_None) tuples, live, in order."""
    q: queue.Queue = queue.Queue()
    tr = tracer or Tracer(queue=q)
    tr.queue = q
    t = ticker.strip().upper()
    result: dict = {"briefing": None}

    def worker():
        try:
            briefing = _run(t, mcp_call, tr)
            result["briefing"] = briefing
            if briefing is not None:
                tr.emit("Orchestrator", "briefing_done", "DONE", "Briefing ready", f"Trace: {briefing.trace_id}")
        except Exception as e:
            tr.emit("Orchestrator", "error", "FAIL", "Briefing failed", str(e)[:300])
        finally:
            q.put(("done", result["briefing"]))

    threading.Thread(target=worker, daemon=True).start()
    buffered_final = None
    while True:
        kind, payload = q.get()
        if kind == "done":
            break
        ev = payload
        if ev["kind"] == "briefing_done":
            buffered_final = ev
            continue
        yield ev, None
    if buffered_final is not None:
        yield buffered_final, result["briefing"]
