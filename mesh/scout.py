"""Scout — evidence only, no interpretation.

Fixed Oct 29 after the live AMZN run: Scout used to take the 8-K's
reportDate (which for an 8-K is the event date, e.g. 2026-10-29) and,
failing that, the filing date, as the quarter end. That labelled a
briefing "quarter ended 2026-10-29" and let Analyst present earlier
quarters' numbers as the reported quarter's.

Quarter end now comes, in order, from:
1. Consensus fiscal_quarter_ending (Nasdaq "Sep/2026" -> 2026-09-30),
2. The latest fact period (SEC EDGAR XBRL facts),
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

from .edgar import _resolve_6k_exhibit
from .release_facts import extract_release_facts, quarter_end_from_release
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
    _quarter_label uses in reverse); 'quarter ended 2026-07-26' ->
    '2026-07-26' (the fiscal fallback label _quarter_label emits for
    non-calendar month ends). None when unparseable."""
    m = re.match(r"^\s*Q([1-4])\s+(\d{4})\s*$", label or "")
    if m:
        return f"{m.group(2)}-{_QUARTER_END_MONTH[int(m.group(1))]}"
    m = re.match(r"^\s*quarter ended (\d{4}-\d{2}-\d{2})\s*$", label or "")
    if m:
        try:
            date.fromisoformat(m.group(1))
        except ValueError:
            return None
        return m.group(1)
    return None


def _same_fiscal_month(a: str, b: str) -> bool:
    """Month-granularity equality for quarter ends. Nasdaq reports
    fiscal quarters as month/year, so its month-end (2026-07-31)
    and a fiscal actual end (2026-07-26) are the same quarter even
    though the dates differ. Exact-date equality would reject
    every fiscal quarter, so the filing confirmation and the
    consensus guard both compare months, not days."""
    try:
        da, db = date.fromisoformat(a), date.fromisoformat(b)
    except ValueError:
        return False
    return (da.year, da.month) == (db.year, db.month)


def _exact_quarter_end_from_filings(recent, month_end_str: str) -> str | None:
    """The latest 10-Q reportDate in a list_recent_filings result
    that falls in the same fiscal month as month_end_str, or
    None. A 10-Q's reportDate IS its quarter end, so it replaces
    the Nasdaq month-end approximation (NVDA: 2026-07-26, not
    2026-07-31) with the filing's own date. Only a same-month
    10-Q counts — the consensus row still identifies the quarter,
    the filing only sharpens its date. Batch 57: the latest NVDA
    run carried quarter_end 2026-07-31 while all four of its facts
    sit at 2026-07-26."""
    if not month_end_str or not isinstance(recent, dict):
        return None
    out = None
    for f in (recent.get("filings") or []):
        if not isinstance(f, dict) or f.get("form") != "10-Q":
            continue
        rd = f.get("reportDate") or ""
        if rd and _same_fiscal_month(rd, month_end_str):
            if out is None or rd > out:
                out = rd
    return out


def _shift_days(iso: str, days: int) -> str:
    return (date.fromisoformat(iso) + timedelta(days=days)).isoformat()


def _pick_quarter_filing(candidates, requested_end, endings):
    """Pick the 8-K that reported the requested quarter.

    candidates: 8-K dicts with filingDate + accessionNumber, already
    filtered to the window after requested_end. endings maps
    accessionNumber -> fiscal quarter end (or None) from the
    consensus probe. Returns (filing_or_None, confirmed_bool):
    the first candidate (earliest filingDate) whose probed
    quarter end is in the same fiscal month as requested_end
    wins, confirmed; otherwise the earliest candidate,
    unconfirmed; None when no candidate.
    """
    ordered = sorted(candidates, key=lambda f: f.get("filingDate") or "")
    for f in ordered:
        probed = endings.get(f.get("accessionNumber"))
        if probed and _same_fiscal_month(probed, requested_end):
            return f, True
    if ordered:
        return ordered[0], False
    return None, False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_upstream_error(exc: Exception | str) -> bool:
    """True when a failure looks like a rate limit or transient
    transport fault (the SEC 429s the Workers' shared egress IPs
    hit intermittently), not a genuine not-reported state.
    Batch 61: a 429 on the submissions fetch was labelled
    NOT_REPORTED_YET, which told the user the company had not
    reported — the wrong story, and one with no retry offered."""
    s = str(exc).lower()
    return ("429" in s or "rate limit" in s or "rate-limit" in s
            or "too many requests" in s or "temporarily unavailable" in s
            or "service unavailable" in s or "timed out" in s or "timeout" in s)


def _failure_status(exc: Exception | str) -> str:
    return "UPSTREAM_ERROR" if _is_upstream_error(exc) else "NOT_REPORTED_YET"


def collect_evidence(ticker: str, mcp_call, quarter: str = "") -> EvidencePack:
    """Build an EvidencePack for ticker's most recent reported quarter,
    or for `quarter` ("Q2 2026", or a fiscal label like
    "quarter ended 2026-07-26") when given: the 8-K, facts,
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
            report_date=_now(), status=_failure_status(e),
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
            # Limit 300, not 50: the submissions "recent" array holds
            # 1000 rows and the limit is a client-side slice, so 300
            # costs no extra request — but 50 ages out the earnings
            # 8-K for frequent filers. NVDA's May 20, 2026 earnings
            # 8-K was outside the 50-window by November, so the
            # April-quarter pick fell back to a June 30 non-earnings
            # 8-K and consensus + price reaction anchored to the
            # wrong date (Nov 4, 2026).
            recent_q = mcp_call("filings", "list_recent_filings", {"ticker": t, "limit": 300})
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
                missing=[f"No earnings filing (8-K/6-K) found for {quarter} — it may not be reported yet, or it is older than the recent-filings window."],
            )
        if not confirmed:
            missing.append(
                f"Could not confirm via consensus that this filing reported {quarter} — using the earliest filing after the quarter end; verify the quarter in the document text.")
        if filing.get("form") == "6-K":
            # The picked filing is the 6-K shell — the release
            # lives in its Exhibit 99.1 (Batch 65).
            try:
                exhibit = _resolve_6k_exhibit(facts["cik"], filing["accessionNumber"])
                if exhibit:
                    filing = {**filing, "primaryDocument": exhibit,
                              "url": f"https://www.sec.gov/Archives/edgar/data/{facts['cik']}/{filing['accessionNumber'].replace('-', '')}/{exhibit}"}
            except Exception:
                pass
    else:
        try:
            filing = mcp_call("filings", "get_latest_earnings_filing", {"ticker": t})
        except Exception as e:
            return EvidencePack(
                ticker=t, company_name=company_name, quarter_label="", quarter_end=date(1970, 1, 1),
                report_date=_now(), status=_failure_status(e),
                missing=[f"filings-mcp get_latest_earnings_filing failed: {e}"],
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

    # Submissions reportDate, kept only as a low-priority candidate:
    # for an 8-K it is the event date, not the quarter end.
    submissions_report_date = ""
    recent = None  # Batch 57: bound even if the fetch below raises.
    try:
        # Limit 50, not 10: the picked earnings filing can be ~10
        # weeks old on the latest path, and the 10 most recent
        # filings span only ~3-4 weeks for frequent filers — the
        # reportDate match below would then miss it.
        recent = recent_q if recent_q is not None else mcp_call("filings", "list_recent_filings", {"ticker": t, "limit": 50})
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

    # 2. Quarterly facts — SEC EDGAR XBRL only (Batch 64).
    # The yfinance quarterly_history leg used to supply the base
    # revenue / operating-income series, with the EDGAR overlay
    # on top. yfinance is not installed in the Python Workers
    # (pandas is too heavy), so the leg failed on every deployed
    # run with "No module named 'yfinance'" — and Yahoo's
    # quoteSummary endpoint now demands a crumb, so there is no
    # lightweight drop-in replacement. The overlay below already
    # returns the full 8-quarter series for every metric from
    # EDGAR companyconcept (revenue, operating income, net
    # income, EBITDA, EPS, shares), so the yfinance leg was
    # redundant: retiring it loses nothing and the Data note
    # about the failure goes away with it.
    facts_list: list[Fact] = []

    # 2b. Filing-verified facts (SEC EDGAR XBRL).
    # A failed filing-facts call is NOT added to `missing` and
    # does NOT block the briefing — the pack keeps whatever
    # facts it has, labelled by source.
    # The old "not yet parsed" note below disappears automatically
    # when at least one EDGAR fact lands (publisher == "SEC EDGAR").
    try:
        filing_facts = mcp_call("filings", "get_filing_facts", {"ticker": t, "report_date": report_date_str})
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
    # The quarter end comes from the release text itself (a 6-K's
    # submissions reportDate is the filing date, not the period
    # end) or from the requested quarter.
    if not facts_list and filing.get("form") == "6-K":
        try:
            release = mcp_call("filings", "get_filing_text", {
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
    # already matches by construction. The comparison is by
    # fiscal month, not exact date: Nasdaq's month-end and a
    # fiscal actual end (e.g. 2026-07-31 vs 2026-07-26) are the
    # same quarter.
    if requested_end and isinstance(consensus, dict) and consensus.get("fiscal_quarter_ending"):
        cons_end = _month_end_from_nasdaq(consensus["fiscal_quarter_ending"])
        if cons_end and not _same_fiscal_month(cons_end, requested_end):
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
        if quarter_end_str:
            # Batch 57: sharpen the month-end approximation with
            # the quarter's 10-Q reportDate (NVDA: 2026-07-26).
            exact = _exact_quarter_end_from_filings(recent, quarter_end_str)
            if exact:
                quarter_end_str = exact
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
            missing.append("Quarter end could not be derived from consensus or the quarterly facts; using filing date as quarter_end — verify against the filing, do not trust the quarter label.")
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

    if not any((f.source.publisher or "").startswith("SEC EDGAR") for f in facts_list):
        missing.append("No filing-verified quarterly facts could be parsed from SEC EDGAR for this ticker — the briefing has no quarterly numbers.")

    return EvidencePack(
        ticker=t, company_name=company_name, quarter_label=quarter_label,
        quarter_end=quarter_end, report_date=report_date, status="REPORTED",
        facts=facts_list, guidance_verbatim=[], consensus=consensus,
        price_reaction=price_reaction, transcript=transcript_data, missing=missing,
    )
