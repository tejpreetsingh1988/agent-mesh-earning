"""Writer — prose only from the approved Analysis + EvidencePack.

Writer introduces NO new numbers: verdict, table rows, drivers, and
risks are copied verbatim from the Analysis; guidance is copied
verbatim from the pack; market reaction is the price claim text
from the Analysis. Sources are the pack's fact sources (deduplicated
by URL+publisher) plus a consensus source entry built from the
pack's consensus source string (no URL invented for it), plus the
transcript source if the pack has one.

The story section is the one place prose is generated: either by
the LLM story layer (mesh.llm.build_story), which is validated
against the verified claims and the transcript and falls back to
a deterministic story on any failure, or — with no OpenRouter key
— by that deterministic story directly. If the Analysis was not
Critic-approved, the caller (Orchestrator) must not call Writer
at all — Writer itself does not re-approve.
"""
from .llm import build_story
from .schemas import Analysis, Briefing, EvidencePack, SourceRef


def write_briefing(pack: EvidencePack, analysis: Analysis, trace_id: str,
                   story_result: dict | None = None, kpi_result: dict | None = None,
                   fine_print_result: dict | None = None) -> Briefing:
    table = [{"claim": c.text, "value": c.value, "derivation": c.derivation} for c in analysis.claims]
    price_claims = [c.text for c in analysis.claims if c.text.startswith("Regular-session close change")]
    market_reaction = price_claims[0] if price_claims else ""

    sources: list[SourceRef] = []
    seen = set()
    for f in pack.facts:
        key = (f.source.url, f.source.publisher)
        if key not in seen:
            seen.add(key)
            sources.append(f.source)
    cons = pack.consensus or {}
    if isinstance(cons, dict) and cons.get("source"):
        key = ("", str(cons["source"]))
        if key not in seen:
            sources.append(SourceRef(url="", publisher=str(cons["source"]), retrieved_at=pack.report_date))
    tr = pack.transcript or {}
    transcript_url = ""
    transcript_excerpt = ""
    if isinstance(tr, dict) and tr.get("status") == "available" and tr.get("url"):
        transcript_url = str(tr["url"])
        transcript_excerpt = str(tr.get("excerpt", "") or "")
        key = (transcript_url, str(tr.get("source", "Transcript")))
        if key not in seen:
            sources.append(SourceRef(url=transcript_url, publisher=str(tr.get("source", "Transcript")),
                                     retrieved_at=pack.report_date))

    if story_result is None:
        story_result = build_story(pack, analysis)

    return Briefing(
        ticker=pack.ticker, quarter_label=pack.quarter_label,
        verdict=analysis.verdict_draft, table=table,
        drivers=list(analysis.drivers), market_reaction=market_reaction,
        guidance_and_watch=list(pack.guidance_verbatim) + list(analysis.risks_and_watch),
        sources=sources, trace_id=trace_id,
        story=story_result.get("story", ""),
        story_model=story_result.get("model", ""),
        story_tokens_in=story_result.get("tokens_in"),
        story_tokens_out=story_result.get("tokens_out"),
        story_latency_s=story_result.get("latency_s"),
        transcript_url=transcript_url,
        transcript_excerpt=transcript_excerpt,
        quarter_end=pack.quarter_end.isoformat() if pack.quarter_end else "",
        fine_print=(fine_print_result or {}).get("items", []) if isinstance(fine_print_result, dict) else [],
        kpis=(kpi_result or {}).get("items", []) if isinstance(kpi_result, dict) else [],
        kpi_source_url=(kpi_result or {}).get("source_url", "") if isinstance(kpi_result, dict) else "",
        diagram=(kpi_result or {}).get("diagram") if isinstance(kpi_result, dict) else None,
    )
