"""Trace events for the activity log.

An event is a plain dict, so it can go over SSE to the UI without
any special serialisation. Every event carries:
- t: seconds since the briefing started (1 decimal, for the log)
- stage: Scout / Analyst / Critic / Writer / Orchestrator
- agent: same as stage, or "MCP" for tool calls
- kind: request, stage_start, stage_done, handoff, mcp_start,
  mcp_done, mcp_failed, retry, warn, critic_verdict, llm_note,
  briefing_done, error, summary
- status: RUNNING, DONE, WARN, FAIL, RETRY, HANDOFF, INFO
- message: one plain sentence, no marketing copy
- detail: optional short factual detail (tool args, counts, URLs)

No event is ever invented: an MCP event is only emitted when a
real MCP call starts/finishes, a stage event only when that stage
actually runs, and the LLM event is honest about v1 — there is no
LLM call in v1, so it says so, rather than faking model activity.
When an LLM step is added later, it should emit llm_start/llm_done
events with model name, tokens, and latency here, in this same format.
"""
import time
from datetime import datetime, timezone


class Tracer:
    def __init__(self, queue=None):
        self.started = time.monotonic()
        self.events: list[dict] = []
        self.queue = queue

    def elapsed(self) -> float:
        return round(time.monotonic() - self.started, 1)

    def emit(self, stage: str, kind: str, status: str, message: str, detail: str = "", agent: str = "") -> dict:
        ev = {
            "t": self.elapsed(),
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "stage": stage,
            "agent": agent or stage,
            "kind": kind,
            "status": status,
            "message": message,
            "detail": detail,
        }
        self.events.append(ev)
        if self.queue is not None:
            self.queue.put(("event", ev))
        return ev


MCP_DESCRIPTIONS = {
    "filings": "filings-mcp — SEC EDGAR (free, no key): company facts, filings, filing text",
    "market": "market-mcp — yfinance, unofficial: price closes, quarterly history, profile",
    "estimates_news": "estimates-news-mcp — Nasdaq calendar (keyless) + Alpha Vantage (key) for consensus; yfinance for calendar/news, context only",
}


def mcp_summary(server: str, tool: str, result) -> str:
    """One-line factual summary of a tool result, for the log. Never
    invents numbers — only counts / dates / statuses actually present."""
    if not isinstance(result, dict):
        return str(result)[:200]
    if "error" in result:
        return f"error: {result['error']}"
    if tool == "get_company_facts":
        return f"{result.get('company_name', '')} (CIK {result.get('cik', '')})"
    if tool == "get_latest_earnings_filing":
        return f"{result.get('form', '')} filed {result.get('filingDate', '')}, accession {result.get('accessionNumber', '')}"
    if tool == "get_quarterly_history":
        rows = [q for q in (result.get("quarters") or []) if q.get("total_revenue") is not None]
        return f"{len(rows)} quarters with revenue, latest {rows[0].get('period_end') if rows else 'none'}"
    if tool == "get_price_reaction":
        closes = result.get("closes") or []
        return f"{len(closes)} closes, {closes[0].get('date') if closes else ''} to {closes[-1].get('date') if closes else ''}"
    if tool == "get_consensus_estimates":
        st = result.get("status")
        if st == "forecast_only":
            return f"forecast-only: EPS ${result.get('eps_estimate')} from {result.get('num_estimates')} estimates, reported not yet available"
        if st in ("available", "available_range"):
            return f"status {st}: EPS estimate {result.get('eps_estimate')}, reported {result.get('eps_reported')}"
        return f"status {st}: {result.get('reason', '')[:120]}"
    if tool == "get_transcript_excerpt":
        if result.get("status") == "available":
            return f"available: {result.get('url', '')}, {len(result.get('takeaways') or [])} takeaways"
        return f"unavailable: {str(result.get('reason', ''))[:120]}"
    if tool == "get_filing_text":
        return f"excerpt {result.get('char_count', '')} chars"
    if tool == "list_recent_filings":
        return f"{len(result.get('filings') or [])} recent filings"
    return f"keys: {', '.join(sorted(result.keys())[:6])}"
