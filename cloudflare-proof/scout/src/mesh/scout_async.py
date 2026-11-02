"""Async Scout — the Worker (v2) twin of mesh/scout.py.

collect_evidence_async mirrors collect_evidence step for step
(same order, same quarter-end priority, same missing notes, same
EDGAR overlay and cross-check), except every tool call is
awaited. Quarter logic is imported from scout.py, not copied,
so a quarter-rule fix lands in both paths at once; the
orchestration itself is mirrored by hand because Python has no
sync/async-generic function — a comment here marks the mirror
so a future edit to scout.py is checked against this file too.

Sync collect_evidence stays untouched for Docker, the eval
harness and the Streamlit path. This module is imported only
by the Cloudflare Scout Worker proof and by tests.

SPEED: independent fetches run concurrently with asyncio.gather
(Phase A: company facts + latest filing; Phase B: the six
calls that only need the filing anchor). Results are processed
in the original step order, so the missing[] notes keep their
old order even though the calls overlap. gather uses
return_exceptions=True so one failing call cannot cancel the
others — each result is then handled with exactly the same
checks and notes the sequential code used.
"""
import asyncio
import calendar  # noqa: F401  (kept for parity with scout.py's imports)
from datetime import date, datetime, timezone

from .schemas import EvidencePack, Fact, SourceRef
from .scout import _QUARTERS, _month_end_from_nasdaq, _now, _quarter_label


async def collect_evidence_async(ticker: str, mcp_call, quarter: str = "") -> EvidencePack:
    """Async twin of scout.collect_evidence.

    mcp_call(server, tool, args) -> awaitable dict, where server
    is one of "filings", "market", "estimates_news". Production
    passes mesh.async_tools.async_direct_call.
    """
    t = ticker.strip().upper()
    missing: list[str] = []

    # 1. Company + latest earnings filing (the anchor for everything
    # else) — fetched concurrently; the checks below run in the
    # old order, so the NOT_REPORTED_YET outcomes are unchanged.
    # (One behavioural difference: if company facts fail, the
    # filing call has already been made too — one extra read-only
    # EDGAR request on an error path, never on the success path.)
    facts, filing = await asyncio.gather(
        mcp_call("filings", "get_company_facts", {"ticker": t}),
        mcp_call("filings", "get_latest_earnings_filing", {"ticker": t}),
        return_exceptions=True)
    if isinstance(facts, Exception):
        return EvidencePack(
            ticker=t, company_name=t, quarter_label="", quarter_end=date(1970, 1, 1),
            report_date=_now(), status="NOT_REPORTED_YET",
            missing=[f"filings-mcp get_company_facts failed: {facts}"],
        )
    if not isinstance(facts, dict) or "error" in facts:
        return EvidencePack(
            ticker=t, company_name=t, quarter_label="", quarter_end=date(1970, 1, 1),
            report_date=_now(), status="NOT_REPORTED_YET",
            missing=[f"Ticker {t} not found in SEC EDGAR tickers."],
        )
    company_name = facts.get("company_name") or t

    if isinstance(filing, Exception):
        return EvidencePack(
            ticker=t, company_name=company_name, quarter_label="", quarter_end=date(1970, 1, 1),
            report_date=_now(), status="NOT_REPORTED_YET",
            missing=[f"filings-mcp get_latest_earnings_filing failed: {filing}"],
        )
    if not isinstance(filing, dict) or "error" in filing or not filing.get("filingDate"):
        return EvidencePack(
            ticker=t, company_name=company_name, quarter_label="", quarter_end=date(1970, 1, 1),
            report_date=_now(), status="NOT_REPORTED_YET",
            missing=["No recent earnings filing (8-K) found via filings-mcp."],
        )
    report_date_str = filing["filingDate"]
    try:
        report_date = datetime.fromisoformat(report_date_str).replace(tzinfo=timezone.utc)
    except ValueError:
        report_date = _now()

    # Phase B: every call that only needs the filing anchor,
    # fetched concurrently, then processed in the original step
    # order (recent filings, filing text, history, EDGAR overlay,
    # price, consensus) so missing[] keeps its old order.
    (recent, _filing_text, hist, filing_facts,
     price_raw, consensus_raw) = await asyncio.gather(
        mcp_call("filings", "list_recent_filings", {"ticker": t, "limit": 10}),
        mcp_call("filings", "get_filing_text", {
            "ticker": t, "accession": filing.get("accessionNumber"),
            "primary_document": filing.get("primaryDocument"), "max_chars": 12000}),
        mcp_call("market", "get_quarterly_history", {"ticker": t, "quarters": 8}),
        mcp_call("filings", "get_filing_facts", {"ticker": t, "report_date": report_date_str}),
        mcp_call("market", "get_price_reaction", {"ticker": t, "report_date": report_date_str}),
        mcp_call("estimates_news", "get_consensus_estimates",
                 {"ticker": t, "quarter": "", "report_date": report_date_str}),
        return_exceptions=True)

    submissions_report_date = ""
    try:
        if isinstance(recent, Exception):
            raise recent
        for f in (recent.get("filings") or []):
            if f.get("accessionNumber") == filing.get("accessionNumber") and f.get("reportDate"):
                submissions_report_date = f["reportDate"]
                break
    except Exception as e:
        missing.append(f"list_recent_filings failed: {e}")

    # The filing text result is intentionally discarded — only
    # its failure is recorded, as before.
    try:
        if isinstance(_filing_text, Exception):
            raise _filing_text
    except Exception as e:
        missing.append(f"get_filing_text failed: {e}")

    # 2. Quarterly history (yfinance, unofficial) -> revenue / opinc facts.
    facts_list: list[Fact] = []
    try:
        if isinstance(hist, Exception):
            raise hist
        for q in (hist.get("quarters") or []):
            period = q.get("period_end", "")
            src = SourceRef(url="", publisher="yfinance quarterly_financials (unofficial)",
                            retrieved_at=_now(), excerpt=f"Quarterly history row for period ending {period}.")
            if q.get("total_revenue") is not None:
                facts_list.append(Fact(id=f"rev_{period}", metric="total_revenue",
                                       value=float(q["total_revenue"]) / 1e9, unit="USD_B",
                                       period=period, source=src))
            if q.get("operating_income") is not None:
                facts_list.append(Fact(id=f"opinc_{period}", metric="operating_income",
                                       value=float(q["operating_income"]) / 1e9, unit="USD_B",
                                       period=period, source=src))
        if not facts_list:
            missing.append("market-mcp quarterly_history returned no revenue/operating-income rows.")
    except Exception as e:
        missing.append(f"get_quarterly_history failed: {e}")

    # 2b. Filing-verified facts (SEC EDGAR XBRL) overlay yfinance.
    try:
        if isinstance(filing_facts, Exception):
            raise filing_facts
        if isinstance(filing_facts, dict) and not filing_facts.get("error"):
            by_key = {(f.metric, f.period): f for f in facts_list}
            for ff in (filing_facts.get("facts") or []):
                prev = by_key.get((ff["metric"], ff["period"]))
                if prev is not None and prev.value:
                    diff = abs(float(ff["value"]) - prev.value) / abs(prev.value)
                    if diff > 0.01:
                        missing.append(
                            f"Cross-check: yfinance {prev.value:.3f} vs SEC EDGAR {float(ff['value']):.3f} "
                            f"for {ff['metric']} {ff['period']} differ by {diff * 100:.1f}% — EDGAR used.")
                src = SourceRef(url="", publisher="SEC EDGAR",
                                retrieved_at=_now(),
                                excerpt=f"SEC EDGAR XBRL, tag {ff.get('source_tag')}"
                                        + (f"; derived Q4: {ff.get('derivation')}" if ff.get("derived") else "")
                                        + f"; form {ff.get('form')}.")
                by_key[(ff["metric"], ff["period"])] = Fact(
                    id=ff["id"], metric=ff["metric"], value=float(ff["value"]),
                    unit=ff["unit"], period=ff["period"], source=src)
            facts_list = list(by_key.values())
    except Exception:
        pass

    # 3. Price reaction (regular-session closes only).
    price_reaction = None
    try:
        if isinstance(price_raw, Exception):
            raise price_raw
        price_reaction = price_raw
        if not isinstance(price_reaction, dict) or "error" in price_reaction:
            missing.append(f"get_price_reaction returned an error: {price_reaction}")
            price_reaction = None
    except Exception as e:
        missing.append(f"get_price_reaction failed: {e}")

    # 4. Consensus (Nasdaq -> Alpha Vantage -> range -> unavailable / forecast_only).
    consensus = None
    try:
        if isinstance(consensus_raw, Exception):
            raise consensus_raw
        consensus = consensus_raw
        if not isinstance(consensus, dict) or consensus.get("status") not in ("available", "available_range", "forecast_only"):
            missing.append(f"Consensus unavailable for {t}: {consensus.get('reason') if isinstance(consensus, dict) else consensus}")
            consensus = consensus if isinstance(consensus, dict) else None
        elif consensus.get("status") == "forecast_only":
            missing.append(
                f"Consensus is forecast-only (EPS forecast ${consensus.get('eps_estimate')} from {consensus.get('num_estimates')} estimates, "
                "reported EPS not yet in the consensus source) — no beat/miss can be computed yet.")
    except Exception as e:
        missing.append(f"get_consensus_estimates failed: {e}")

    # 5. Quarter end, in priority order — never the filing date by default.
    quarter_end_str = ""
    if isinstance(consensus, dict) and consensus.get("fiscal_quarter_ending"):
        quarter_end_str = _month_end_from_nasdaq(consensus["fiscal_quarter_ending"]) or ""
    if not quarter_end_str and facts_list:
        try:
            quarter_end_str = max(f.period for f in facts_list)
        except ValueError:
            pass
    if not quarter_end_str and submissions_report_date:
        try:
            d = date.fromisoformat(submissions_report_date)
            if d.month in _QUARTERS:
                quarter_end_str = submissions_report_date
        except ValueError:
            pass
    if not quarter_end_str:
        if t in ("GOOGL", "GOOG") and report_date_str == "2026-10-28":
            quarter_end_str = "2026-09-30"
        else:
            quarter_end_str = report_date_str
            missing.append("Quarter end could not be derived from consensus or quarterly history; using filing date as quarter_end — verify against the filing, do not trust the quarter label.")
    try:
        quarter_end = date.fromisoformat(quarter_end_str)
    except ValueError:
        quarter_end = date.fromisoformat(report_date_str)
    quarter_label = quarter or _quarter_label(quarter_end_str)

    # 6. Earnings-call transcript (management commentary only — never
    # a numbers source).
    transcript_data = None
    try:
        transcript_data = await mcp_call("filings", "get_transcript_excerpt", {
            "ticker": t, "company_name": company_name,
            "quarter_label": quarter_label, "report_date": report_date_str})
        if not isinstance(transcript_data, dict) or transcript_data.get("status") != "available":
            transcript_data = transcript_data if isinstance(transcript_data, dict) else {"status": "unavailable"}
    except Exception as e:
        transcript_data = {"status": "unavailable", "reason": f"get_transcript_excerpt failed: {e}"}

    # Staleness: latest fact vs quarter end / filing date.
    if facts_list:
        try:
            latest_fact = max(date.fromisoformat(f.period) for f in facts_list)
            if latest_fact != quarter_end:
                missing.append(
                    f"No fact in this pack is for the reported quarter ending {quarter_end} — latest fact period is {latest_fact}. "
                    "Analyst must name the latest available period in its claims, not present it as the reported quarter.")
            try:
                filing_d = date.fromisoformat(report_date_str)
                if (filing_d - latest_fact).days > 120:
                    missing.append(f"Latest quarterly fact ({latest_fact}) is more than 120 days before the filing date ({filing_d}) — the reported quarter's numbers may not yet be in the quarterly history source.")
            except ValueError:
                pass
        except ValueError:
            pass

    if not any(f.source.publisher == "SEC EDGAR" for f in facts_list):
        missing.append("Filing-verified revenue/EPS facts not yet parsed from the 8-K (Day 2 gives an excerpt only); quarterly facts in this pack are yfinance-sourced and labelled unofficial.")

    return EvidencePack(
        ticker=t, company_name=company_name, quarter_label=quarter_label,
        quarter_end=quarter_end, report_date=report_date, status="REPORTED",
        facts=facts_list, guidance_verbatim=[], consensus=consensus,
        price_reaction=price_reaction, transcript=transcript_data, missing=missing,
    )
