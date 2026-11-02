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
}

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


def fetch_concept(cik: int, tag: str) -> dict:
    """Fetch one companyconcept payload from data.sec.gov.

    gzip is handled explicitly — the trial's first run failed
    because Accept-Encoding: gzip was sent but the bytes were
    never decompressed. Here no gzip is requested, and a gzipped
    response is decompressed if one arrives anyway.
    """
    url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/us-gaap/{tag}.json"
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
    """Units dict for one tag inside a companyfacts payload, or {}."""
    try:
        return companyfacts["facts"]["us-gaap"][tag]["units"] or {}
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


def derive_q4_rows(concept: dict, metric: str) -> list[dict]:
    """Derive Q4 as FY minus 9-month YTD, from one concept payload.

    A 10-K FY row is a full year, never a quarter, so it must not
    be presented as Q4. But if the same concept also has a 10-Q
    row for the first 9 months (duration ~240–290 days, fp Q3)
    ending in the same year, Q4 = FY value − YTD value, with
    period_end = FY end. The derived row is labelled `derived`
    so no caller can mistake it for a filed quarterly figure.
    Returns newest first.
    """
    ytd = {}
    fy = {}
    for unit, rows in (concept.get("units") or {}).items():
        for row in rows:
            duration = _duration_days(row)
            if duration is None:
                continue
            try:
                end_year = date.fromisoformat(row["end"]).year
            except Exception:
                continue
            if row.get("form") == "10-Q" and 240 <= duration <= 290:
                ytd[end_year] = row
            elif row.get("form") == "10-K" and 330 <= duration <= 370:
                fy[end_year] = row
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


def get_filing_facts_for_ticker(ticker: str, report_date: str = "") -> dict:
    """MCP-tool shape: ticker -> filing-verified facts.

    Resolves the CIK via mesh.edgar, runs get_quarterly_facts,
    and converts rows to the shape Scout expects: revenue and
    operating income in USD_B (filed USD / 1e9), EPS in USD,
    each with the XBRL tag that produced it. Derived Q4 rows
    keep their derivation note. A metric with no quarterly row
    is reported in `missing`, never invented.
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
        for tag in tags:
            try:
                payload = fetch(cik, tag)
            except Exception:
                continue
            rows = _rows_from_payload(payload, metric)
            if rows:
                candidates.append((tag, rows))
        picked = pick_latest_tag(candidates)
        fallback_tried = False
        if companyfacts_fetch is not None and needs_companyfacts_fallback(picked, report_date):
            cf = _companyfacts()
            fallback_tried = cf is not None
            if cf:
                for tag in tags:
                    rows = _rows_from_payload(
                        {"units": companyfacts_tag_units(cf, tag)}, metric)
                    if rows:
                        candidates.append((tag, rows))
                picked = pick_latest_tag(candidates)
        if picked:
            tag, rows = picked
            result[metric] = {"tag": tag, "rows": rows[:limit]}
        else:
            note = f"No quarterly-duration 10-Q row for {metric} (tried: {', '.join(tags)})"
            if fallback_tried:
                note += " (companyfacts fallback also empty)"
            missing.append(note)
    result["missing"] = missing
    return result
