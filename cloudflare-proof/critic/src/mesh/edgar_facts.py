"""Filing-verified facts from SEC EDGAR XBRL — Phase 1, step 1.

Why this module exists: the top-20 trial (Nov 1, 2026) proved a
single XBRL tag does NOT repeat across companies, and a naive
"latest row wins" pick is wrong. Two failure modes, both seen live:

1. Alternate tags. AMZN and MA have no `Revenues` tag; LLY and JPM
   have no `OperatingIncomeLoss`; BRK and MA have no
   `EarningsPerShareDiluted`. Each company files under a different
   tag for the same concept, so this module tries a tag list in
   order and records which tag actually produced the fact.
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


def get_filing_facts_for_ticker(ticker: str) -> dict:
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
    quarterly = get_quarterly_facts(facts["cik"])
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


def get_quarterly_facts(cik: int, fetch=fetch_concept, limit: int = 8) -> dict:
    """Try each alternate tag per metric, in order, until one
    yields quarterly rows. Returns {metric: {tag, rows}} plus a
    `missing` list for metrics with no quarterly row at all.

    `fetch` is injectable so tests (and the eval harness) can
    pass a fake that returns fixture payloads instead of hitting
    data.sec.gov. SEC's fair-access rule is 10 requests/second;
    callers should sleep ~0.1s between concept fetches.
    """
    result: dict = {}
    missing: list[str] = []
    for metric, tags in ALTERNATE_TAGS.items():
        found = None
        tried = []
        for tag in tags:
            tried.append(tag)
            try:
                payload = fetch(cik, tag)
                rows = parse_concept_rows(payload, metric)
            except Exception:
                continue
            if rows:
                rows = list(rows)
                seen = {r["period_end"] for r in rows}
                for derived in derive_q4_rows(payload, metric):
                    if derived["period_end"] not in seen:
                        rows.append(derived)
                rows.sort(key=lambda r: r["period_end"] or "", reverse=True)
                found = {"tag": tag, "rows": rows[:limit]}
                break
        if found:
            result[metric] = found
        else:
            missing.append(f"No quarterly-duration 10-Q row for {metric} (tried: {', '.join(tried)})")
    result["missing"] = missing
    return result
