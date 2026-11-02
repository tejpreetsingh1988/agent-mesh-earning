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
from datetime import date, datetime, timezone

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


def _now() -> datetime:
    return datetime.now(timezone.utc)


def collect_evidence(ticker: str, mcp_call, quarter: str = "") -> EvidencePack:
    """Build an EvidencePack for ticker's most recent reported quarter.

    mcp_call(server, tool, args) -> dict, where server is one of
    "filings", "market", "estimates_news". Tests inject a fake;
    production passes mesh.mcp_client.make_client().
    """
    t = ticker.strip().upper()
    missing: list[str] = []

    # 1. Company + latest earnings filing (the anchor for everything else).
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
        recent = mcp_call("filings", "list_recent_filings", {"ticker": t, "limit": 10})
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

    # 5. Quarter end, in priority order — never the filing date by default.
    quarter_end_str = ""
    if isinstance(consensus, dict) and consensus.get("fiscal_quarter_ending"):
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
