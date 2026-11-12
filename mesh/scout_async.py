"""Async Scout — the Worker (v2) twin of mesh/scout.py.

collect_evidence_async mirrors collect_evidence step for step
(same order, same quarter-end priority, same missing notes, same
EDGAR overlay and cross-check), except every tool call is
awaited. Most quarter logic is imported from scout.py — but
NOT all of it: the consensus guard below and the quarter-end
chain are hand-mirrored, and Batch 20 proved the mirror drifts
(the sync guard went month-granular while this one stayed
exact-date, silently discarding every fiscal quarter's
consensus). A future edit to scout.py's quarter logic MUST be
checked against this file too, and vice versa.

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

from .async_tools import async_resolve_6k_exhibit
from .release_facts import extract_release_facts, quarter_end_from_release
from .schemas import EvidencePack, Fact, SourceRef
from .scout import (_QUARTERS, _exact_quarter_end_from_filings, _failure_status, _month_end_from_nasdaq, _now,
                     _pick_quarter_filing, _quarter_end_from_label,
                     _quarter_label, _same_fiscal_month, _shift_days)


async def collect_evidence_async(ticker: str, mcp_call, quarter: str = "") -> EvidencePack:
    """Async twin of scout.collect_evidence.

    mcp_call(server, tool, args) -> awaitable dict, where server
    is one of "filings", "market", "estimates_news". Production
    passes mesh.async_tools.async_direct_call.
    """
    t = ticker.strip().upper()
    missing: list[str] = []

    # A requested quarter, parsed once and used by every step below
    # (same rules as the sync path — see scout.py).
    requested_end = _quarter_end_from_label(quarter) if quarter else None
    if quarter and not requested_end:
        missing.append(f"Unrecognized quarter label {quarter!r} — using the most recent reported quarter.")
        quarter = ""  # Fall back fully: the bogus label must not survive as quarter_label.

    # 1. Company + earnings filing (the anchor for everything
    # else). Latest path: fetched concurrently, as before.
    # Requested quarter: sequential selection (list filings, probe
    # consensus per candidate) — the filing must be known before
    # Phase B, so it cannot join the gather.
    recent_q = None
    if requested_end:
        try:
            facts = await mcp_call("filings", "get_company_facts", {"ticker": t})
        except Exception as e:
            facts = e
        filing = None
    else:
        facts, filing = await asyncio.gather(
            mcp_call("filings", "get_company_facts", {"ticker": t}),
            mcp_call("filings", "get_latest_earnings_filing", {"ticker": t}),
            return_exceptions=True)
    if isinstance(facts, Exception):
        return EvidencePack(
            ticker=t, company_name=t, quarter_label="", quarter_end=date(1970, 1, 1),
            report_date=_now(), status=_failure_status(facts),
            missing=[f"filings-mcp get_company_facts failed: {facts}"],
        )
    if not isinstance(facts, dict) or "error" in facts:
        return EvidencePack(
            ticker=t, company_name=t, quarter_label="", quarter_end=date(1970, 1, 1),
            report_date=_now(), status="NOT_REPORTED_YET",
            missing=[f"Ticker {t} not found in SEC EDGAR tickers."],
        )
    company_name = facts.get("company_name") or t

    if requested_end:
        try:
            # Limit 300, not 50: the submissions "recent" array holds
            # 1000 rows and the limit is a client-side slice, so 300
            # costs no extra request — but 50 ages out the earnings
            # 8-K for frequent filers. NVDA's May 20, 2026 earnings
            # 8-K was outside the 50-window by November, so the
            # April-quarter pick fell back to a June 30 non-earnings
            # 8-K and consensus + price reaction anchored to the
            # wrong date (Nov 4, 2026).
            recent_q = await mcp_call("filings", "list_recent_filings", {"ticker": t, "limit": 300})
        except Exception as e:
            return EvidencePack(
                ticker=t, company_name=company_name, quarter_label=quarter, quarter_end=date.fromisoformat(requested_end),
                report_date=_now(), status=_failure_status(e),
                missing=[f"Cannot select a filing for {quarter}: list_recent_filings failed: {e}"],
            )
        if not isinstance(recent_q, dict) or "error" in recent_q:
            return EvidencePack(
                ticker=t, company_name=company_name, quarter_label=quarter, quarter_end=date.fromisoformat(requested_end),
                report_date=_now(), status=_failure_status(recent_q.get("error", "") if isinstance(recent_q, dict) else ""),
                missing=[f"Cannot select a filing for {quarter}: list_recent_filings returned an error: {recent_q.get('error') if isinstance(recent_q, dict) else 'not a dict'}."],
            )
        window_end = _shift_days(requested_end, 75)
        candidates = [f for f in (recent_q.get("filings") or [])
                      if f.get("form") == "8-K" and f.get("filingDate")
                      and requested_end < f["filingDate"] <= window_end]
        if not candidates:
            # Batch 65: foreign private issuers report on 6-K —
            # same window, same consensus confirmation.
            candidates = [f for f in (recent_q.get("filings") or [])
                          if f.get("form") == "6-K" and f.get("filingDate")
                          and requested_end < f["filingDate"] <= window_end]
        endings: dict[str, str | None] = {}
        for cand in sorted(candidates, key=lambda f: f["filingDate"])[:5]:
            try:
                probe = await mcp_call("estimates_news", "get_consensus_estimates",
                                       {"ticker": t, "quarter": "", "report_date": cand["filingDate"]})
                endings[cand["accessionNumber"]] = (
                    _month_end_from_nasdaq(probe["fiscal_quarter_ending"])
                    if isinstance(probe, dict) and probe.get("fiscal_quarter_ending") else None)
            except Exception:
                endings[cand["accessionNumber"]] = None
        filing, confirmed = _pick_quarter_filing(candidates, requested_end, endings)
        if filing is None:
            return EvidencePack(
                ticker=t, company_name=company_name, quarter_label=quarter, quarter_end=date.fromisoformat(requested_end),
                report_date=_now(), status="NOT_REPORTED_YET",
                missing=[f"No earnings filing (8-K/6-K) found for {quarter} — it may not be reported yet, or it is older than the recent-filings window."],
            )
        if not confirmed:
            missing.append(
                f"Could not confirm via consensus that this filing reported {quarter} — using the earliest filing after the quarter end; verify the quarter in the document text.")
        if filing.get("form") == "6-K":
            # The picked filing is the 6-K shell — the release
            # lives in its Exhibit 99.1 (Batch 65).
            try:
                exhibit = await async_resolve_6k_exhibit(facts["cik"], filing["accessionNumber"])
                if exhibit:
                    filing = {**filing, "primaryDocument": exhibit,
                              "url": f"https://www.sec.gov/Archives/edgar/data/{facts['cik']}/{filing['accessionNumber'].replace('-', '')}/{exhibit}"}
            except Exception:
                pass
    else:
        if isinstance(filing, Exception):
            return EvidencePack(
                ticker=t, company_name=company_name, quarter_label="", quarter_end=date(1970, 1, 1),
                report_date=_now(), status=_failure_status(filing),
                missing=[f"filings-mcp get_latest_earnings_filing failed: {filing}"],
            )
        if not isinstance(filing, dict) or "error" in filing or not filing.get("filingDate"):
            return EvidencePack(
                ticker=t, company_name=company_name, quarter_label="", quarter_end=date(1970, 1, 1),
                report_date=_now(), status=_failure_status(filing.get("error", "") if isinstance(filing, dict) else ""),
                missing=["No recent earnings filing (8-K) found via filings-mcp."
                         + (f" Upstream error: {filing['error']}" if isinstance(filing, dict) and filing.get("error") else "")],
            )
    report_date_str = filing["filingDate"]
    try:
        report_date = datetime.fromisoformat(report_date_str).replace(tzinfo=timezone.utc)
    except ValueError:
        report_date = _now()

    # Phase B: every call that only needs the filing anchor,
    # fetched concurrently, then processed in the original step
    # order (recent filings, filing text, EDGAR facts, price,
    # consensus) so missing[] keeps its old order. Batch 64:
    # the yfinance quarterly_history call is gone (see step 2).
    (recent, _filing_text, filing_facts,
     price_raw, consensus_raw) = await asyncio.gather(
        # Limit 50, not 10: the picked earnings filing can be ~10
        # weeks old on the latest path, and the 10 most recent
        # filings span only ~3-4 weeks for frequent filers — the
        # reportDate match below would then miss it.
        asyncio.sleep(0, result=recent_q) if requested_end else mcp_call("filings", "list_recent_filings", {"ticker": t, "limit": 50}),
        mcp_call("filings", "get_filing_text", {
            "ticker": t, "accession": filing.get("accessionNumber"),
            "primary_document": filing.get("primaryDocument"), "max_chars": 12000}),
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

    # 2. Quarterly facts — SEC EDGAR XBRL only (Batch 64).
    # The yfinance quarterly_history leg is retired: yfinance is
    # not installed in the Python Workers and Yahoo's quoteSummary
    # endpoint now demands a crumb, so there is no lightweight
    # replacement — and the overlay below already returns the
    # full 8-quarter series for every metric from EDGAR
    # companyconcept, so the leg was redundant.
    facts_list: list[Fact] = []

    # 2b. Filing-verified facts (SEC EDGAR XBRL).
    try:
        if isinstance(filing_facts, Exception):
            raise filing_facts
        if isinstance(filing_facts, dict) and not filing_facts.get("error"):
            by_key = {(f.metric, f.period): f for f in facts_list}
            for ff in (filing_facts.get("facts") or []):
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

    # 2c. Release-text facts (Batch 65): foreign private issuers
    # file 6-K, not 10-Q, so there is no XBRL series. When the
    # overlay found nothing and the earnings filing is a 6-K,
    # parse the Financial Highlights table of its Exhibit 99.1.
    if not facts_list and filing.get("form") == "6-K":
        try:
            release = await mcp_call("filings", "get_filing_text", {
                "ticker": t, "accession": filing.get("accessionNumber"),
                "primary_document": filing.get("primaryDocument"), "max_chars": 60000})
            exhibit_text = (release or {}).get("excerpt", "") if isinstance(release, dict) else ""
            qe = date.fromisoformat(requested_end) if requested_end else quarter_end_from_release(exhibit_text)
            if qe is None:
                missing.append("6-K earnings release: could not determine the quarter end from the release text — no release-text facts emitted.")
            else:
                parsed = extract_release_facts(exhibit_text, ticker=t, quarter_end=qe,
                                               exhibit_url=filing.get("url", ""), filing_date=report_date_str)
                for ff in parsed.get("facts", []):
                    src = SourceRef(url=ff.get("url", ""), publisher=ff.get("publisher", "SEC EDGAR"),
                                    retrieved_at=_now(),
                                    excerpt=f"SEC EDGAR 6-K exhibit 99.1, {ff.get('source_tag')}; form 6-K.")
                    facts_list.append(Fact(id=ff["id"], metric=ff["metric"], value=float(ff["value"]),
                                           unit=ff["unit"], period=ff["period"], source=src))
                missing.extend(parsed.get("missing", []))
                if parsed.get("facts"):
                    missing.append(
                        f"Quarterly figures from the earnings release for the quarter ended {qe} (6-K exhibit 99.1) — "
                        f"{company_name} files 6-K, not 10-Q, so there is no XBRL series; figures are release text, verified against the exhibit.")
        except Exception as e:
            missing.append(f"6-K release-text parse failed: {e}")

    # Requested quarter: truncate facts to the quarter end (see
    # scout.py); no fact for the quarter end itself means there
    # is nothing to brief.
    if requested_end:
        facts_list = [f for f in facts_list if f.period <= requested_end]
        if not any(f.period == requested_end for f in facts_list):
            return EvidencePack(
                ticker=t, company_name=company_name, quarter_label=quarter,
                quarter_end=date.fromisoformat(requested_end), report_date=report_date,
                status="NOT_REPORTED_YET",
                missing=[f"No quarterly facts for the quarter ending {requested_end} ({quarter}) — it may be older than the available history."],
            )

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

    # Requested quarter: discard a consensus row for a different
    # quarter end (see scout.py). Month granularity, like the
    # sync guard: Nasdaq's month-end and a fiscal actual end
    # (e.g. 2026-04-30 vs 2026-04-26) are the same quarter.
    # Batch 20 fix: this guard was exact-date while the sync
    # guard went month-granular, so every fiscal quarter's
    # consensus was discarded on the cloud path.
    if requested_end and isinstance(consensus, dict) and consensus.get("fiscal_quarter_ending"):
        cons_end = _month_end_from_nasdaq(consensus["fiscal_quarter_ending"])
        if cons_end and not _same_fiscal_month(cons_end, requested_end):
            missing.append(f"Consensus row is for the quarter ending {cons_end}, not the requested {requested_end} — consensus not used for beat/miss.")
            consensus = None

    # 5. Quarter end, in priority order — never the filing date by default.
    # A requested quarter overrides the whole chain (see scout.py).
    quarter_end_str = ""
    if requested_end:
        quarter_end_str = requested_end
    elif isinstance(consensus, dict) and consensus.get("fiscal_quarter_ending"):
        quarter_end_str = _month_end_from_nasdaq(consensus["fiscal_quarter_ending"]) or ""
        if quarter_end_str:
            # Batch 57: sharpen the month-end approximation with
            # the quarter's 10-Q reportDate (NVDA: 2026-07-26).
            exact = _exact_quarter_end_from_filings(recent, quarter_end_str)
            if exact:
                quarter_end_str = exact
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

    if not any((f.source.publisher or "").startswith("SEC EDGAR") for f in facts_list):
        missing.append("No filing-verified quarterly facts could be parsed from SEC EDGAR for this ticker — the briefing has no quarterly numbers.")

    return EvidencePack(
        ticker=t, company_name=company_name, quarter_label=quarter_label,
        quarter_end=quarter_end, report_date=report_date, status="REPORTED",
        facts=facts_list, guidance_verbatim=[], consensus=consensus,
        price_reaction=price_reaction, transcript=transcript_data, missing=missing,
    )
