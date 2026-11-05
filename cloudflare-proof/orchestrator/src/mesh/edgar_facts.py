"""Filing-verified facts from SEC EDGAR XBRL — Phase 1, step 1.

Why this module exists: the top-20 trial (Nov 1, 2026) proved a
single XBRL tag does NOT repeat across companies, and a naive
"latest row wins" pick is wrong. Two failure modes, both seen live:

1. Alternate tags. AMZN and MA have no `Revenues` tag; LLY and JPM
   have no `OperatingIncomeLoss`; BRK and MA have no
   `EarningsPerShareDiluted`. Each company files under a different
   tag for the same concept, so this module tries a tag list and
   records which tag actually produced the fact. The tag is
   chosen by recency, not by list order: the first tag with any
   rows is WRONG when a retired tag still has old rows — MSFT's
   `Revenues` tag has quarterly rows from 2009–2010, so it used
   to beat the current
   `RevenueFromContractWithCustomerExcludingAssessedTax` tag
   that was never even tried, and a briefing labelled Q3 2026
   carried 2010 revenue (see pick_latest_tag).
2. Year-to-date rows. A 10-Q can carry a 6- or 9-month cumulative
   value (NVDA `Revenues` $96.2B was 6 months, not a quarter).
   A quarterly fact must come from a row whose start-to-end
   duration is roughly one quarter (60–100 days), from a 10-Q.
   A 10-K FY row is a full year, never a quarter, and is never
   presented as one — Q4 must be derived as FY minus the 9-month
   YTD figure, which this module does NOT yet do (see below).

Scope, stated plainly:
- This step parses companyconcept rows into quarterly facts and
  is unit-tested with fixtures. It does NOT yet replace
  yfinance in Scout — that wiring, plus the Q4 derivation and a
  cross-check against the press release, is the next step.
- Fiscal calendars differ (NVDA Q2 ends in July, COST's year
  ends in August), so the period is always the row's `end`
  date, never a calendar quarter label.
- Values are in the row's unit as filed (usually USD, sometimes
  USD/shares for EPS). Callers must not assume billions.
"""
from __future__ import annotations

import gzip
import json
import urllib.request
from datetime import date

# Tag lists in priority order. The first tag that returns a
# quarterly-duration row wins; the tag used is recorded on the fact.
ALTERNATE_TAGS = {
    "total_revenue": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
        "TotalRevenues",
        "RevenuesNetOfInterestExpense",
    ],
    "operating_income": [
        "OperatingIncomeLoss",
        "OperatingIncomeLossBeforeMinorityInterest",
    ],
    "gaap_eps": [
        "EarningsPerShareDiluted",
        "EarningsPerShareBasic",
    ],
    "net_income": [
        "NetIncomeLoss",
        "ProfitLoss",
    ],
    # Depreciation & amortization: the D&A half of derived
    # EBITDA. No single tag covers every filer — DUK-style
    # filers use DepreciationDepletionAndAmortization while
    # MSFT-style filers use Depreciation — so both are tried
    # and pick_latest_tag (recency) decides per company.
    "depreciation_amortization": [
        "DepreciationDepletionAndAmortization",
        "Depreciation",
    ],
    # Cash-flow items: operating cash flow and CapEx are
    # YTD figures in 10-Qs, so they get the same
    # YTD-difference treatment as D&A (see below).
    "operating_cash_flow": [
        "NetCashProvidedByUsedInOperatingActivities",
    ],
    "capex": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
    ],
    # Balance-sheet items: instants, not flows — parsed by
    # parse_instant_rows, never by the duration filter.
    "cash_and_equivalents": [
        "CashAndCashEquivalentsAtCarryingValue",
    ],
    "short_term_investments": [
        "ShortTermInvestments",
    ],
    # Buybacks: two tag conventions across filers — the
    # current PaymentsToRepurchaseCommonStock and the
    # older PaymentsForRepurchaseOfCommonStock (MSFT
    # uses the older one). Recency pick decides.
    "buybacks": [
        "PaymentsToRepurchaseCommonStock",
        "PaymentsForRepurchaseOfCommonStock",
    ],
    # Shares outstanding: a DEI cover-page tag, not
    # us-gaap. The "dei:" prefix selects the taxonomy
    # (see split_taxonomy); the cover date is the
    # period — roughly a month after the quarter end.
    "shares_outstanding": [
        "dei:EntityCommonStockSharesOutstanding",
    ],
}

# Metrics whose rows are point-in-time balances, parsed by
# parse_instant_rows instead of _rows_from_payload.
INSTANT_METRICS = {"cash_and_equivalents", "short_term_investments",
                   "shares_outstanding"}


def split_taxonomy(tag: str) -> tuple[str, str]:
    """Split a possibly taxonomy-prefixed tag.

    "dei:EntityCommonStockSharesOutstanding" ->
    ("dei", "EntityCommonStockSharesOutstanding").
    A bare tag means us-gaap. The prefix travels with
    the tag string so fetch signatures never change.
    """
    if ":" in tag:
        taxonomy, bare = tag.split(":", 1)
        return taxonomy, bare
    return "us-gaap", tag

USER_AGENT = "Agent Mesh Research Lab research@example.com"


def _duration_days(row: dict) -> int | None:
    try:
        start = date.fromisoformat(row["start"])
        end = date.fromisoformat(row["end"])
        return (end - start).days
    except Exception:
        return None


def parse_concept_rows(concept: dict, metric: str) -> list[dict]:
    """Extract quarterly-duration 10-Q rows from one companyconcept
    payload, newest first. Rows are returned as plain dicts so
    callers (and tests) need no Pydantic model yet.

    A row qualifies only if: form is 10-Q, it has start/end, and
    its duration is 60–100 days. Instant rows (no start), 10-K FY
    rows, and YTD rows are all excluded — silently, by design,
    because including them is how the trial produced a $96.2B
    'quarter' for NVDA.
    """
    out = []
    for unit, rows in (concept.get("units") or {}).items():
        for row in rows:
            if row.get("form") != "10-Q":
                continue
            duration = _duration_days(row)
            if duration is None or not (60 <= duration <= 100):
                continue
            out.append({
                "metric": metric,
                "value": row.get("val"),
                "unit": unit,
                "period_end": row.get("end"),
                "period_start": row.get("start"),
                "duration_days": duration,
                "form": row.get("form"),
                "filed": row.get("filed"),
                "accession": row.get("accn"),
            })
    # Dedupe: the same quarter is often re-filed as a comparative
    # figure in the next year's 10-Q (same start/end/value, new
    # accession). Keep the latest-filed version of each period;
    # if a restatement changed the value, the latest filing wins.
    out.sort(key=lambda r: r["filed"] or "", reverse=True)
    seen = set()
    deduped = []
    for row in out:
        key = (row["period_start"], row["period_end"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    deduped.sort(key=lambda r: r["period_end"] or "", reverse=True)
    return deduped


def parse_instant_rows(concept: dict, metric: str) -> list[dict]:
    """Balance-sheet rows: point-in-time, no duration.

    Cash and short-term investments are balances at the
    quarter end, not flows, so the 60–100-day duration
    filter would discard every one. A row qualifies if:
    form is 10-Q or 10-K (a 10-K balance is the Q4
    balance), it has an end date, and it has NO start
    (instant rows carry none). Dedupe is per fiscal
    quarter (fy, fp) when those fields exist — a
    cover-page share count re-filed by an amendment
    has a different cover date for the same quarter,
    and period-end dedupe would keep both and break
    the Analyst's month-pairing; latest filed wins.
    Without fy/fp, dedupe falls back to period end.
    Newest first.
    """
    out = []
    for unit, rows in (concept.get("units") or {}).items():
        for row in rows:
            if row.get("form") not in ("10-Q", "10-K"):
                continue
            if row.get("start"):
                continue
            end = row.get("end")
            if not end or row.get("val") is None:
                continue
            out.append({
                "metric": metric,
                "value": row.get("val"),
                "unit": unit,
                "period_end": end,
                "period_start": None,
                "duration_days": None,
                "form": row.get("form"),
                "filed": row.get("filed"),
                "accession": row.get("accn"),
                "fy": row.get("fy"),
                "fp": row.get("fp"),
            })
    out.sort(key=lambda r: r["filed"] or "", reverse=True)
    seen = set()
    deduped = []
    for row in out:
        key = (row["fy"], row["fp"]) if row["fy"] and row["fp"] else row["period_end"]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    deduped.sort(key=lambda r: r["period_end"] or "", reverse=True)
    return deduped


def fetch_concept(cik: int, tag: str) -> dict:
    """Fetch one companyconcept payload from data.sec.gov.

    gzip is handled explicitly — the trial's first run failed
    because Accept-Encoding: gzip was sent but the bytes were
    never decompressed. Here no gzip is requested, and a gzipped
    response is decompressed if one arrives anyway.
    A "dei:"-prefixed tag selects the DEI taxonomy.
    """
    taxonomy, bare = split_taxonomy(tag)
    url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/{taxonomy}/{bare}.json"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return json.loads(raw)


def fetch_companyfacts(cik: int) -> dict:
    """Fetch the whole companyfacts payload for one CIK.

    This is the fallback source for the Visa case (Nov 2, 2026):
    EDGAR's per-tag companyconcept endpoint returned EMPTY units
    (valid JSON, HTTP 200) for Visa's current revenue and
    operating-income tags, while companyfacts held full current
    data for the same tags. The payload is a few MB and holds
    every tag, so callers must read ONLY the ALTERNATE_TAGS they
    need from it — never parse all ~600 tags.
    """
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return json.loads(raw)


def companyfacts_tag_units(companyfacts: dict, tag: str) -> dict:
    """Units dict for one tag inside a companyfacts payload, or {}.

    A "dei:"-prefixed tag reads the DEI taxonomy section.
    """
    taxonomy, bare = split_taxonomy(tag)
    try:
        return companyfacts["facts"][taxonomy][bare]["units"] or {}
    except Exception:
        return {}


# A companyconcept pick is "implausibly stale" when its newest
# row is more than this many days before the earnings report
# date. 400 days is deliberately generous: a normal pick sits
# within ~120 days of the filing, and even a ticker whose XBRL
# lags a quarter sits within ~180 days — so the fallback fires
# only for genuinely broken picks like Visa's 2019 rows.
STALE_PICK_DAYS = 400


def needs_companyfacts_fallback(picked, report_date: str | None) -> bool:
    """True when the companyconcept pick must not be trusted.

    Fires on an empty pick (no tag had rows) or on a stale pick
    (newest row > STALE_PICK_DAYS before report_date). With no
    report_date the staleness check cannot run, so only an empty
    pick triggers — callers that know the filing date should
    always pass it, or a stale pick silently survives.
    """
    if picked is None:
        return True
    if not report_date:
        return False
    try:
        ref = date.fromisoformat(report_date[:10])
        latest = date.fromisoformat(picked[1][0]["period_end"])
    except Exception:
        return False
    return (ref - latest).days > STALE_PICK_DAYS


def _rows_from_payload(payload: dict, metric: str) -> list[dict]:
    """Quarterly rows (plus derived Q4s) from one concept payload.

    Shared by the companyconcept loop and the companyfacts
    fallback loop: both payloads carry the same `units` shape,
    so a synthetic {"units": units} companyfacts tag payload
    parses identically. Returns newest first, or [] when the
    payload holds no quarterly-duration 10-Q row.
    """
    rows = parse_concept_rows(payload, metric)
    if not rows:
        return []
    rows = list(rows)
    seen = {r["period_end"] for r in rows}
    for derived in derive_q4_rows(payload, metric):
        if derived["period_end"] not in seen:
            rows.append(derived)
    rows.sort(key=lambda r: r["period_end"] or "", reverse=True)
    return rows


def _fiscal_year(row: dict) -> int | None:
    """The fiscal year a concept row belongs to.

    Prefer the row's own `fy` field; fall back to the calendar
    year of its end date for rows that lack one. The fallback is
    WRONG for fiscal calendars (an FY ending in January and its
    9-month YTD ending the previous October share a fiscal year
    but not a calendar year), so it is only a last resort.
    """
    fy = row.get("fy")
    if isinstance(fy, int):
        return fy
    try:
        return int(fy)
    except (TypeError, ValueError):
        pass
    try:
        return date.fromisoformat(row["end"]).year
    except Exception:
        return None


def derive_q4_rows(concept: dict, metric: str) -> list[dict]:
    """Derive Q4 as FY minus 9-month YTD, from one concept payload.

    A 10-K FY row is a full year, never a quarter, so it must not
    be presented as Q4. But if the same concept also has a 10-Q
    row for the first 9 months (duration ~240–290 days, fp Q3)
    of the SAME fiscal year, Q4 = FY value − YTD value, with
    period_end = FY end. The derived row is labelled `derived`
    so no caller can mistake it for a filed quarterly figure.
    Returns newest first.

    The pairing key is the fiscal year (the row's `fy` field),
    NOT the calendar year of the end date. Keying by end-date
    year silently pairs the wrong rows for fiscal calendars:
    NVDA's FY2025 10-K ends Jan 2025 while FY2026's 9-month
    YTD ends Oct 2025 — same calendar year, different fiscal
    years — and FY − YTD came out as −$17.3B of "revenue", a
    negative fact that shipped in live packs (Nov 4, 2026)
    while the real Q4 FY2026 row (Jan 2026) never appeared.
    """
    ytd = {}
    fy = {}
    for unit, rows in (concept.get("units") or {}).items():
        for row in rows:
            duration = _duration_days(row)
            if duration is None:
                continue
            year = _fiscal_year(row)
            if year is None:
                continue
            fp = row.get("fp")
            if row.get("form") == "10-Q" and 240 <= duration <= 290:
                if fp and fp != "Q3":
                    continue
                ytd[year] = row
            elif row.get("form") == "10-K" and 330 <= duration <= 370:
                if fp and fp != "FY":
                    continue
                fy[year] = row
    out = []
    for year in sorted(set(ytd) & set(fy)):
        y, f = ytd[year], fy[year]
        try:
            value = float(f["val"]) - float(y["val"])
        except Exception:
            continue
        out.append({
            "metric": metric, "value": value, "unit": "USD",
            "period_end": f["end"], "period_start": y["end"],
            "duration_days": _duration_days({"start": y["end"], "end": f["end"]}),
            "form": "10-K (derived Q4)", "filed": f.get("filed"),
            "accession": f.get("accn"), "derived": True,
            "derivation": f"FY {f['val']} minus 9-month YTD {y['val']}",
        })
    out.sort(key=lambda r: r["period_end"] or "", reverse=True)
    return out


def derive_discrete_ytd_rows(concept: dict, metric: str) -> list[dict]:
    """Derive discrete quarters from YTD cash-flow rows.

    Many filers report cash-flow items (D&A, operating cash
    flow, CapEx) only as year-to-date figures: Q1 covers 3
    months, Q2 covers 6, Q3 covers 9. The parsed quarterly
    rows miss Q2/Q3 for them (durations 150–290 days, not
    60–100). Within one fiscal year — the row's `fy` field,
    which handles fiscal calendars like NVDA's —
    discrete Q2 = YTD Q2 minus YTD Q1, and discrete Q3 =
    YTD Q3 minus YTD Q2. Only consecutive fiscal periods
    difference: a gap (Q3 with no Q2) yields no row, never
    a 6-month figure presented as a quarter. A negative
    difference (a restatement artifact) is skipped, never
    emitted. Within one (fy, fp) the latest-filed row wins;
    on a filed-date tie the longer duration wins, which is
    the YTD figure when a filer reports both a discrete
    and a YTD row for the same quarter (MSFT does).
    Rows are newest first, in the parsed-row shape.
    """
    ytd: dict[tuple, dict] = {}
    for unit, rows in (concept.get("units") or {}).items():
        if unit != "USD":
            continue
        for row in rows:
            if row.get("form") != "10-Q":
                continue
            fy, fp = row.get("fy"), row.get("fp")
            if fp not in ("Q1", "Q2", "Q3"):
                continue
            try:
                duration = _duration_days(row)
                value = float(row["val"])
            except (TypeError, ValueError):
                continue
            if duration is None:
                continue
            key = (fy, fp)
            prev = ytd.get(key)
            if prev is None or (row.get("filed") or "") > (prev["filed"] or "") or (
                    (row.get("filed") or "") == (prev["filed"] or "")
                    and duration > (prev["duration"] or 0)):
                ytd[key] = {"fy": fy, "fp": fp, "value": value,
                            "end": row.get("end"), "filed": row.get("filed"),
                            "duration": duration, "accession": row.get("accn")}
    out = []
    for fy in {k[0] for k in ytd}:
        q1, q2, q3 = ytd.get((fy, "Q1")), ytd.get((fy, "Q2")), ytd.get((fy, "Q3"))
        for cur, prev in ((q2, q1), (q3, q2)):
            if cur is None or prev is None:
                continue
            value = cur["value"] - prev["value"]
            if value < 0:
                continue
            out.append({
                "metric": metric, "value": value, "unit": "USD",
                "period_end": cur["end"], "period_start": prev["end"],
                "duration_days": _duration_days({"start": prev["end"], "end": cur["end"]}),
                "form": "10-Q", "filed": cur["filed"],
                "accession": cur["accession"], "derived": True,
                "derivation": f"YTD {cur['value']} minus YTD {prev['value']}",
            })
    out.sort(key=lambda r: r["period_end"] or "", reverse=True)
    return out


def get_filing_facts_for_ticker(ticker: str, report_date: str = "") -> dict:
    """MCP-tool shape: ticker -> filing-verified facts.

    Resolves the CIK via mesh.edgar, runs get_quarterly_facts,
    and converts rows to the shape Scout expects: revenue,
    operating income, net income, and derived EBITDA in USD_B
    (filed USD / 1e9), EPS in USD, each with the XBRL tag
    that produced it. Derived Q4 and EBITDA rows keep their
    derivation note. A metric with no quarterly row is
    reported in `missing`, never invented.
    """
    from . import edgar as edgar_mod

    facts = edgar_mod.get_company_facts(ticker)
    if "error" in facts:
        return facts
    quarterly = get_quarterly_facts(
        facts["cik"], report_date=report_date or None,
        companyfacts_fetch=fetch_companyfacts)
    out = []
    for metric, data in quarterly.items():
        if metric == "missing":
            continue
        for row in data["rows"]:
            if metric == "gaap_eps":
                value, unit = float(row["value"]), "USD"
            elif metric == "shares_outstanding":
                value, unit = float(row["value"]) / 1e9, "shares_B"
            else:
                value, unit = float(row["value"]) / 1e9, "USD_B"
            out.append({
                "id": f"edgar_{metric}_{row['period_end']}" + ("_derived" if row.get("derived") else ""),
                "metric": metric, "value": value, "unit": unit,
                "period": row["period_end"], "source_tag": data["tag"],
                "derived": bool(row.get("derived")),
                "derivation": row.get("derivation", ""),
                "form": row["form"], "filed": row.get("filed"),
            })
    return {"ticker": facts["ticker"], "company_name": facts["company_name"],
            "cik": facts["cik"], "facts": out, "missing": quarterly["missing"]}


def pick_latest_tag(candidates):
    """Pick the tag whose rows reach the most recent quarter.

    candidates: iterable of (tag, rows) in priority order, rows
    newest-first (as parse_concept_rows returns). Recency wins:
    a tag whose latest period is strictly later displaces the
    current best; on a tie the earlier-priority tag stands.
    Returns (tag, rows) or None when no candidate has rows.

    This is the MSFT fix: `Revenues` rows end in 2010 while the
    current contract-revenue tag reaches 2026, so recency — not
    list order — must decide, or a current-quarter briefing
    inherits decade-old facts.
    """
    best = None
    for tag, rows in candidates:
        if not rows:
            continue
        latest = rows[0].get("period_end") or ""
        if best is None or latest > best[1]:
            best = (tag, latest, rows)
    return (best[0], best[2]) if best else None


def get_quarterly_facts(cik: int, fetch=fetch_concept, limit: int = 8,
                        report_date: str | None = None,
                        companyfacts_fetch=None) -> dict:
    """Try every alternate tag per metric and keep the one whose
    rows reach the most recent quarter (see pick_latest_tag).
    Returns {metric: {tag, rows}} plus a `missing` list for
    metrics with no quarterly row at all.

    `fetch` is injectable so tests (and the eval harness) can
    pass a fake that returns fixture payloads instead of hitting
    data.sec.gov. SEC's fair-access rule is 10 requests/second;
    callers should sleep ~0.1s between concept fetches.

    `report_date` (the earnings filing date) plus
    `companyfacts_fetch` enable the companyfacts fallback: when
    a metric's companyconcept pick is empty or implausibly stale
    (see needs_companyfacts_fallback), the same tags are re-read
    from the one companyfacts payload and the pick is redone.
    With companyfacts_fetch left unset there is no fallback —
    that is what keeps existing tests hermetic.
    """
    result: dict = {}
    missing: list[str] = []
    picked_payloads: dict[str, dict] = {}
    # The companyfacts payload is fetched lazily, at most once
    # per run, and only when some metric's pick actually needs
    # it — working tickers never pay the few-MB download.
    _cf: list = []

    def _companyfacts():
        if not _cf:
            try:
                _cf.append(companyfacts_fetch(cik))
            except Exception:
                _cf.append(None)
        return _cf[0]

    for metric, tags in ALTERNATE_TAGS.items():
        candidates = []
        tag_payloads: dict[str, dict] = {}
        for tag in tags:
            try:
                payload = fetch(cik, tag)
            except Exception:
                continue
            tag_payloads[tag] = payload
            rows = (parse_instant_rows(payload, metric) if metric in INSTANT_METRICS
                    else _rows_from_payload(payload, metric))
            if rows:
                candidates.append((tag, rows))
        picked = pick_latest_tag(candidates)
        fallback_tried = False
        if companyfacts_fetch is not None and needs_companyfacts_fallback(picked, report_date):
            cf = _companyfacts()
            fallback_tried = cf is not None
            if cf:
                for tag in tags:
                    cf_payload = {"units": companyfacts_tag_units(cf, tag)}
                    rows = (parse_instant_rows(cf_payload, metric) if metric in INSTANT_METRICS
                            else _rows_from_payload(cf_payload, metric))
                    if rows:
                        candidates.append((tag, rows))
                        tag_payloads[tag] = cf_payload
                picked = pick_latest_tag(candidates)
        if picked:
            tag, rows = picked
            result[metric] = {"tag": tag, "rows": rows[:limit]}
            picked_payloads[metric] = tag_payloads.get(tag, {})
        else:
            note = f"No quarterly-duration 10-Q row for {metric} (tried: {', '.join(tags)})"
            if fallback_tried:
                note += " (companyfacts fallback also empty)"
            missing.append(note)
    apply_derived_metrics(result, picked_payloads, limit)
    result["missing"] = missing
    return result


def apply_derived_metrics(result: dict, picked_payloads: dict, limit: int) -> None:
    """Shared by the sync and async quarterly-facts paths.

    Fills discrete quarters for YTD cash-flow items and
    derives EBITDA, free cash flow, and combined cash +
    short-term investments, mutating `result` in place.
    Kept in one place so the cloud (async) path and the
    sync path can never drift apart again.
    """
    # --- YTD-difference fill (Batch 21) ---
    # Cash-flow items (D&A, operating cash flow, CapEx, buybacks)
    # are YTD figures in 10-Qs: parsed rows cover Q1 and
    # any filer that reports discrete quarters; this fill
    # adds Q2/Q3 for YTD-only filers, deduped by period
    # with the parsed row winning.
    for ytd_metric in ("depreciation_amortization", "operating_cash_flow", "capex", "buybacks"):
        entry = result.get(ytd_metric)
        if entry is None:
            continue
        rows = list(entry["rows"])
        have = {r["period_end"] for r in rows}
        payload = picked_payloads.get(ytd_metric)
        if payload:
            for row in derive_discrete_ytd_rows(payload, ytd_metric):
                if row["period_end"] not in have:
                    rows.append(row)
                    have.add(row["period_end"])
        rows.sort(key=lambda r: r["period_end"] or "", reverse=True)
        entry["rows"] = rows[:limit]
    # --- Derived EBITDA (Batch 21) ---
    # EBITDA = operating income + D&A per period. No GAAP
    # XBRL tag for EBITDA exists, so it is always derived,
    # and the derivation rides on the row like derived Q4
    # rows — which is what lets the Critic re-check it
    # from the same filing facts instead of taking it on
    # trust.
    da_entry = result.get("depreciation_amortization")
    if da_entry is not None:
        da_rows = list(da_entry["rows"])
        op_rows = result.get("operating_income", {}).get("rows", [])
        da_by_period = {r["period_end"]: r for r in da_rows}
        ebitda_rows = []
        for r in op_rows:
            d = da_by_period.get(r["period_end"])
            if d is None:
                continue
            try:
                value = float(r["value"]) + float(d["value"])
            except (TypeError, ValueError):
                continue
            ebitda_rows.append({
                "metric": "ebitda", "value": value, "unit": "USD",
                "period_end": r["period_end"], "period_start": r.get("period_start"),
                "duration_days": r.get("duration_days"),
                "form": r["form"], "filed": r.get("filed"),
                "accession": r.get("accession"), "derived": True,
                "derivation": f"Operating income {r['value']} + depreciation & amortization {d['value']}",
            })
        if ebitda_rows:
            ebitda_rows.sort(key=lambda r: r["period_end"] or "", reverse=True)
            result["ebitda"] = {
                "tag": f"derived (OperatingIncomeLoss + {da_entry['tag']})",
                "rows": ebitda_rows[:limit]}
    # --- Derived free cash flow (Batch 21) ---
    # FCF = operating cash flow minus CapEx per period.
    # CapEx XBRL values are positive payment amounts
    # (verified live on MSFT), so the subtraction is
    # direct — no sign flip.
    ocf_rows = result.get("operating_cash_flow", {}).get("rows", [])
    cap_rows = result.get("capex", {}).get("rows", [])
    cap_by_period = {r["period_end"]: r for r in cap_rows}
    fcf_rows = []
    for r in ocf_rows:
        c = cap_by_period.get(r["period_end"])
        if c is None:
            continue
        try:
            value = float(r["value"]) - float(c["value"])
        except (TypeError, ValueError):
            continue
        fcf_rows.append({
            "metric": "free_cash_flow", "value": value, "unit": "USD",
            "period_end": r["period_end"], "period_start": r.get("period_start"),
            "duration_days": r.get("duration_days"),
            "form": r["form"], "filed": r.get("filed"),
            "accession": r.get("accession"), "derived": True,
            "derivation": f"Operating cash flow {r['value']} minus CapEx {c['value']}",
        })
    if fcf_rows:
        fcf_rows.sort(key=lambda r: r["period_end"] or "", reverse=True)
        result["free_cash_flow"] = {
            "tag": "derived (NetCashProvidedByUsedInOperatingActivities - PaymentsToAcquirePropertyPlantAndEquipment)",
            "rows": fcf_rows[:limit]}
    # --- Combined cash + short-term investments (Batch 21) ---
    # Filed balances summed per period end; only periods
    # where BOTH exist combine (a cash-only sum would
    # mislabel itself as cash + investments).
    cash_rows = result.get("cash_and_equivalents", {}).get("rows", [])
    st_rows = result.get("short_term_investments", {}).get("rows", [])
    st_by_period = {r["period_end"]: r for r in st_rows}
    combined_rows = []
    for r in cash_rows:
        s = st_by_period.get(r["period_end"])
        if s is None:
            continue
        try:
            value = float(r["value"]) + float(s["value"])
        except (TypeError, ValueError):
            continue
        combined_rows.append({
            "metric": "cash_and_st_investments", "value": value, "unit": "USD",
            "period_end": r["period_end"], "period_start": None,
            "duration_days": None,
            "form": r["form"], "filed": r.get("filed"),
            "accession": r.get("accession"), "derived": True,
            "derivation": f"Cash {r['value']} + short-term investments {s['value']}",
        })
    if combined_rows:
        combined_rows.sort(key=lambda r: r["period_end"] or "", reverse=True)
        result["cash_and_st_investments"] = {
            "tag": "derived (CashAndCashEquivalentsAtCarryingValue + ShortTermInvestments)",
            "rows": combined_rows[:limit]}
