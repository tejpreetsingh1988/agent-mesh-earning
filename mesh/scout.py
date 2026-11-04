"""Scout — evidence only, no interpretation.

Fixed Oct 29 after the live AMZN run: Scout used to take the 8-K's
reportDate (which for an 8-K is the event date, e.g. 2026-10-29) and,
failing that, the filing date, as the quarter end. That labelled a
briefing "quarter ended 2026-10-29" and let Analyst present earlier
quarters' numbers as the reported quarter's.

Quarter end now comes, in order, from:
1. Consensus fiscal_quarter_ending (Nasdaq "Sep/2026" -> 2026-09-30),
2. The latest non-null quarterly_history period,
3. A submissions reportDate only if its month is a quarter-end
   month (3, 6, 9, 12),
and never from the filing date. If none of those give a quarter
end, Scout says so in `missing` and uses the filing date only as a
last resort, labelled as unverified.

Staleness is also recorded: if the latest quarterly fact is more
than 90 days before the filing date, or if no fact matches the
quarter end, Scout puts that in `missing` (Analyst copies pack.missing
into risks, so the briefing shows it). Scout never fills the gap
with an earlier quarter and calls it the reported quarter.
"""
import calendar
import re
from datetime import date, datetime, timedelta, timezone

from .schemas import EvidencePack, Fact, SourceRef

_QUARTERS = {3: "Q1", 6: "Q2", 9: "Q3", 12: "Q4"}
_MONTH_ABBR = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
               "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}


def _quarter_label(period_end: str) -> str:
    try:
        d = date.fromisoformat(period_end)
    except ValueError:
        return f"quarter ended {period_end}"
    q = _QUARTERS.get(d.month)
    if q:
        return f"{q} {d.year}"
    return f"quarter ended {period_end}"


def _month_end_from_nasdaq(fiscal: str) -> str | None:
    """'Sep/2026' -> '2026-09-30'. Returns None if unparseable."""
    try:
        mon, year = fiscal.split("/")
        month = _MONTH_ABBR[mon.strip()]
        y = int(year.strip())
        return f"{y}-{month:02d}-{calendar.monthrange(y, month)[1]:02d}"
    except Exception:
        return None


_QUARTER_END_MONTH = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}


def _quarter_end_from_label(label: str) -> str | None:
    """'Q2 2026' -> '2026-06-30' (calendar quarters, the same mapping
    _quarter_label uses in reverse). None when unparseable."""
    m = re.match(r"^\s*Q([1-4])\s+(\d{4})\s*$", label or "")
    if not m:
        return None
    return f"{m.group(2)}-{_QUARTER_END_MONTH[int(m.group(1))]}"


def _shift_days(iso: str, days: int) -> str:
    return (date.fromisoformat(iso) + timedelta(days=days)).isoformat()


def _pick_quarter_filing(candidates, requested_end, endings):
    """Pick the 8-K that reported the requested quarter.

    candidates: 8-K dicts with filingDate + accessionNumber, already
    filtered to the window after requested_end. endings maps
    accessionNumber -> fiscal quarter end (or None) from the
    consensus probe. Returns (filing_or_None, confirmed_bool):
    the first candidate (earliest filingDate) whose probed
    quarter end equals requested_end wins, confirmed; otherwise
    the earliest candidate, unconfirmed; None when no candidate.
    """
    ordered = sorted(candidates, key=lambda f: f.get("filingDate") or "")
    for f in ordered:
        if endings.get(f.get("accessionNumber")) == requested_end:
            return f, True
    if ordered:
        return ordered[0], False
    return None, False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def collect_evidence(ticker: str, mcp_call, quarter: str = "") -> EvidencePack:
    """Build an EvidencePack for ticker's most recent reported quarter,
    or for `quarter` ("Q2 2026") when given: the 8-K, facts,
    consensus and transcript are then anchored to that quarter
    instead of the latest one. A quarter label used to be a label
    override only — since Batch 7 it selects the quarter for real,
    and a quarter with no filing or no facts returns
    NOT_REPORTED_YET rather than latest data under an old label.

    mcp_call(server, tool, args) -> dict, where server is one of
    "filings", "market", "estimates_news". Tests inject a fake;
    production passes mesh.mcp_client.make_client().
    """
    t = ticker.strip().upper()
    missing: list[str] = []

    # A requested quarter, parsed once and used by every step below.
    requested_end = _quarter_end_from_label(quarter) if quarter else None
    if quarter and not requested_end:
        missing.append(f"Unrecognized quarter label {quarter!r} — using the most recent reported quarter.")
        quarter = ""  # Fall back fully: the bogus label must not survive as quarter_label.

    # 1. Company + earnings filing (the anchor for everything else).
    # Latest path: the most recent 8-K, as before. Requested
    # quarter: the 8-K that reported that quarter — candidates
    # are 8-Ks filed in the 75 days after the quarter end, and
    # the consensus probe (Nasdaq fiscal quarter ending) confirms
    # which one reported it. The probe costs at most 5 keyless
    # Nasdaq calls and usually 1; the Alpha Vantage cross-check
    # only runs when a key is configured (never on Workers).
    try:
        facts = mcp_call("filings", "get_company_facts", {"ticker": t})
    except Exception as e:
        return EvidencePack(
            ticker=t, company_name=t, quarter_label="", quarter_end=date(1970, 1, 1),
            report_date=_now(), status="NOT_REPORTED_YET",
            missing=[f"filings-mcp get_company_facts failed: {e}"],
        )
    if not isinstance(facts, dict) or "error" in facts:
        return EvidencePack(
            ticker=t, company_name=t, quarter_label="", quarter_end=date(1970, 1, 1),
            report_date=_now(), status="NOT_REPORTED_YET",
            missing=[f"Ticker {t} not found in SEC EDGAR tickers."],
        )
    company_name = facts.get("company_name") or t

    recent_q = None
    filing = None
    if requested_end:
        try:
            recent_q = mcp_call("filings", "list_recent_filings", {"ticker": t, "limit": 50})
        except Exception as e:
            return EvidencePack(
                ticker=t, company_name=company_name, quarter_label=quarter, quarter_end=date.fromisoformat(requested_end),
                report_date=_now(), status="NOT_REPORTED_YET",
                missing=[f"Cannot select a filing for {quarter}: list_recent_filings failed: {e}"],
            )
        if not isinstance(recent_q, dict) or "error" in recent_q:
            return EvidencePack(
                ticker=t, company_name=company_name, quarter_label=quarter, quarter_end=date.fromisoformat(requested_end),
                report_date=_now(), status="NOT_REPORTED_YET",
                missing=[f"Cannot select a filing for {quarter}: list_recent_filings returned an error."],
            )
        window_end = _shift_days(requested_end, 75)
        candidates = [f for f in (recent_q.get("filings") or [])
                      if f.get("form") == "8-K" and f.get("filingDate")
                      and requested_end < f["filingDate"] <= window_end]
        endings: dict[str, str | None] = {}
        for cand in sorted(candidates, key=lambda f: f["filingDate"])[:5]:
            try:
                probe = mcp_call("estimates_news", "get_consensus_estimates",
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
                missing=[f"No earnings filing (8-K) found for {quarter} — it may not be reported yet, or it is older than the recent-filings window."],
            )
        if not confirmed:
            missing.append(
                f"Could not confirm via consensus that this 8-K reported {quarter} — using the earliest 8-K after the quarter end; verify the quarter in the document text.")
    else:
        try:
            filing = mcp_call("filings", "get_latest_earnings_filing", {"ticker": t})
        except Exception as e:
            return EvidencePack(
                ticker=t, company_name=company_name, quarter_label="", quarter_end=date(1970, 1, 1),
                report_date=_now(), status="NOT_REPORTED_YET",
                missing=[f"filings-mcp get_latest_earnings_filing failed: {e}"],
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

    # Submissions reportDate, kept only as a low-priority candidate:
    # for an 8-K it is the event date, not the quarter end.
    submissions_report_date = ""
    try:
        recent = recent_q if recent_q is not None else mcp_call("filings", "list_recent_filings", {"ticker": t, "limit": 10})
        for f in (recent.get("filings") or []):
            if f.get("accessionNumber") == filing.get("accessionNumber") and f.get("reportDate"):
                submissions_report_date = f["reportDate"]
                break
    except Exception as e:
        missing.append(f"list_recent_filings failed: {e}")

    try:
        mcp_call("filings", "get_filing_text", {
            "ticker": t, "accession": filing.get("accessionNumber"),
            "primary_document": filing.get("primaryDocument"), "max_chars": 12000})
    except Exception as e:
        missing.append(f"get_filing_text failed: {e}")

    # 2. Quarterly history (yfinance, unofficial) -> revenue / opinc facts.
    facts_list: list[Fact] = []
    try:
        hist = mcp_call("market", "get_quarterly_history", {"ticker": t, "quarters": 8})
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
    # Same metric + period: the EDGAR fact wins, because it is
    # filing-verified; yfinance remains the fallback for periods
    # EDGAR lacks. A failed filing-facts call is NOT added to
    # `missing` and does NOT block the briefing — the pack keeps
    # its yfinance facts, labelled unofficial, exactly as before.
    # The old "not yet parsed" note below disappears automatically
    # when at least one EDGAR fact lands (publisher == "SEC EDGAR").
    try:
        filing_facts = mcp_call("filings", "get_filing_facts", {"ticker": t, "report_date": report_date_str})
        if isinstance(filing_facts, dict) and not filing_facts.get("error"):
            by_key = {(f.metric, f.period): f for f in facts_list}
            for ff in (filing_facts.get("facts") or []):
                # Cross-check: if yfinance already had this period
                # and EDGAR disagrees by more than 1%, say so in
                # `missing` (which Analyst copies into risks).
                # EDGAR still wins — the note is transparency,
                # not a reason to prefer the unofficial figure.
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

    # Requested quarter: facts after the quarter end belong to
    # later quarters and must not leak in — the Analyst's "latest"
    # is the requested quarter only when the list is truncated
    # here. No fact for the requested quarter end itself means
    # there is nothing to brief, not a latest-quarter briefing
    # under an old label.
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
        price_reaction = mcp_call("market", "get_price_reaction", {"ticker": t, "report_date": report_date_str})
        if not isinstance(price_reaction, dict) or "error" in price_reaction:
            missing.append(f"get_price_reaction returned an error: {price_reaction}")
            price_reaction = None
    except Exception as e:
        missing.append(f"get_price_reaction failed: {e}")

    # 4. Consensus (Nasdaq -> Alpha Vantage -> range -> unavailable / forecast_only).
    # Quarter is passed as "" here: Nasdaq needs report_date only, and
    # the fiscal quarter ending it returns is what sets quarter_end below.
    consensus = None
    try:
        consensus = mcp_call("estimates_news", "get_consensus_estimates",
                             {"ticker": t, "quarter": "", "report_date": report_date_str})
        if not isinstance(consensus, dict) or consensus.get("status") not in ("available", "available_range", "forecast_only"):
            missing.append(f"Consensus unavailable for {t}: {consensus.get('reason') if isinstance(consensus, dict) else consensus}")
            consensus = consensus if isinstance(consensus, dict) else None
        elif consensus.get("status") == "forecast_only":
            missing.append(
                f"Consensus is forecast-only (EPS forecast ${consensus.get('eps_estimate')} from {consensus.get('num_estimates')} estimates, "
                "reported EPS not yet in the consensus source) — no beat/miss can be computed yet.")
    except Exception as e:
        missing.append(f"get_consensus_estimates failed: {e}")

    # Requested quarter: a consensus row for a different quarter
    # end must not feed a beat/miss. This only bites on the
    # unconfirmed-filing fallback — a confirmed filing's row
    # already matches by construction.
    if requested_end and isinstance(consensus, dict) and consensus.get("fiscal_quarter_ending"):
        cons_end = _month_end_from_nasdaq(consensus["fiscal_quarter_ending"])
        if cons_end and cons_end != requested_end:
            missing.append(f"Consensus row is for the quarter ending {cons_end}, not the requested {requested_end} — consensus not used for beat/miss.")
            consensus = None

    # 5. Quarter end, in priority order — never the filing date by default.
    # A requested quarter overrides the whole chain: the chain could
    # otherwise disagree (consensus missing -> latest fact period),
    # and its "using filing date" note would be wrong for a
    # requested quarter.
    quarter_end_str = ""
    if requested_end:
        quarter_end_str = requested_end
    elif isinstance(consensus, dict) and consensus.get("fiscal_quarter_ending"):
        quarter_end_str = _month_end_from_nasdaq(consensus["fiscal_quarter_ending"]) or ""
    if not quarter_end_str and facts_list:
        # Latest fact period (facts are period_end dates from history).
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
    # a numbers source). Unavailable is a normal outcome: transcripts
    # publish a day or so after the call, and Fool's slug discovery
    # does not cover every company. The briefing continues without it.
    transcript_data = None
    try:
        transcript_data = mcp_call("filings", "get_transcript_excerpt", {
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
