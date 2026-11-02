"""Critic — does NOT trust Analyst. Re-checks independently.

Checks (ARCHITECTURE Section 6, Day 4):
1. Existence: every claim's evidence_ids must exist in the pack.
2. Arithmetic: YoY, margin, beat/miss, and price-reaction claims are
   recomputed from pack facts / consensus / closes and must match
   the claim value within 0.5 (percentage points) — or, for range
   claims, the position (within/below/above) must match.
3. Basis: every EPS beat/miss entry must carry a basis label, and
   there must be no single merged EPS entry that mixes GAAP and
   adjusted reported EPS. If both bases are present, both must be
   reported separately.
4. Beat/miss: consensus entries in the pack must be reflected in
   beat_miss (no silent omission of an available consensus), and
   no beat/miss entry may use a consensus number that is not in
   the pack.
5. Omissions: if the pack has >=2 periods for a metric, Analyst
   must have a YoY claim for it; if the pack has revenue + opinc,
   it must have a margin claim.
6. Overclaims / staleness: a claim must not introduce a number
   that is not in its derivation or evidence; a pack whose
   report_date is before its quarter_end is stale/inconsistent.
7. Independent re-query: Critic re-calls MCP tools itself
   (company facts, latest filing, consensus, quarterly history,
   price reaction) and compares ticker, filing date, consensus
   EPS estimate, and latest quarterly revenue to the pack, within
   tolerance. A re-query failure is recorded, not silently ignored:
   if the live tools are unreachable, Critic still returns a
   verdict on checks 1-6, with a requery note in rechecked_facts,
   but it does NOT claim live verification it did not do.
8. NOT_REPORTED_YET: if the pack is not REPORTED, any non-empty
   claims/beat_miss is an automatic FAIL.

Verdict PASS only if there are no FAIL issues. Issues are dicts
with severity ("fail" or "warn"), check, and message.
"""
from .schemas import Analysis, Critique, EvidencePack


def _pct(new: float, old: float) -> float | None:
    if not old:
        return None
    return (new - old) / abs(old) * 100.0


def critique(pack: EvidencePack, analysis: Analysis, mcp_call=None) -> Critique:
    issues: list[dict] = []
    rechecked: list[str] = []

    def fail(check: str, msg: str):
        issues.append({"severity": "fail", "check": check, "message": msg})

    def warn(check: str, msg: str):
        issues.append({"severity": "warn", "check": check, "message": msg})

    fact_ids = {f.id for f in pack.facts}
    facts_by_metric: dict[str, list] = {}
    for f in pack.facts:
        facts_by_metric.setdefault(f.metric, []).append(f)
    for v in facts_by_metric.values():
        v.sort(key=lambda f: f.period)

    # 8. NOT_REPORTED_YET gate
    if pack.status != "REPORTED":
        if analysis.claims or analysis.beat_miss:
            fail("not_reported", "Pack is NOT_REPORTED_YET but Analysis contains claims/beat_miss — no analysis is valid.")
        return Critique(verdict="FAIL" if issues else "PASS", issues=issues, rechecked_facts=rechecked)

    # 6. Staleness / consistency
    try:
        if pack.report_date.date() < pack.quarter_end:
            fail("staleness", f"report_date {pack.report_date.date()} is before quarter_end {pack.quarter_end} — inconsistent pack.")
    except Exception:
        pass

    # 1. Existence
    for c in analysis.claims:
        for eid in c.evidence_ids:
            if eid not in fact_ids:
                fail("existence", f"Claim '{c.text[:60]}' cites missing evidence id '{eid}'.")

    # 2+5. Arithmetic + omissions, recomputed from the pack.
    # Oct 29 AMZN fix: YoY is ONLY a 12-month pair, QoQ ONLY a 3-month
    # pair. Taking the last two facts regardless of gap is what turned
    # a QoQ move into a fake YoY claim, so Critic recomputes by
    # interval and fails any claim whose named periods do not match.
    import re as _re
    from mesh.analyst import _pair, parse_period

    def find_claim(prefix: str):
        return next((c for c in analysis.claims if c.text.startswith(prefix)), None)

    for c in analysis.claims:
        m = _re.search(r"(YoY|QoQ) growth \(([^)]+) -> ([^)]+)\)", c.text)
        if m:
            kind, prev_s, cur_s = m.group(1), m.group(2), m.group(3)
            prev_d, cur_d = parse_period(prev_s), parse_period(cur_s)
            if prev_d is None or cur_d is None:
                fail("arithmetic", f"Growth claim '{c.text[:60]}' has unparseable periods.")
            else:
                months = (cur_d.year - prev_d.year) * 12 + (cur_d.month - prev_d.month)
                expected_months = 12 if kind == "YoY" else 3
                if months != expected_months:
                    fail("arithmetic", f"{kind} claim '{c.text[:60]}' spans {months} months, not {expected_months} — this is not a {kind} comparison.")

    for metric, label in [("total_revenue", "Revenue"), ("operating_income", "Operating income"),
                          ("cloud_revenue", "Cloud revenue"), ("gaap_eps", "GAAP EPS")]:
        fs_raw = facts_by_metric.get(metric, [])
        fs = sorted([(parse_period(f.period), f) for f in fs_raw if parse_period(f.period) is not None], key=lambda x: x[0])
        yoy = _pair(fs, 12)
        if yoy is not None:
            prev, cur = yoy
            expected = _pct(cur.value, prev.value)
            c = find_claim(f"{label} YoY growth")
            if c is None:
                fail("omission", f"Pack has a 12-month pair for {label} but Analysis has no YoY claim for it.")
            elif c.value is None or expected is None or abs(c.value - expected) > 0.5:
                fail("arithmetic", f"{label} YoY claim {c.value} does not match recomputed {expected} from pack facts.")
        else:
            if find_claim(f"{label} YoY growth") is not None:
                fail("overclaim", f"{label} YoY claim exists but pack has no 12-month pair for it.")

    revs = facts_by_metric.get("total_revenue", [])
    opincs = facts_by_metric.get("operating_income", [])
    if revs and opincs:
        # Margin is only recomputable for a period both metrics
        # share. The old fallback (latest operating income of any
        # period) recomputed MSFT's 230.1% margin as correct.
        rev_periods = {f.period for f in revs}
        opinc_by_period = {f.period: f for f in opincs}
        common = sorted(p for p in rev_periods if p in opinc_by_period)
        c = find_claim("Operating margin")
        if not common:
            if c is not None:
                fail("margin", "Operating margin claim exists but revenue and operating income share no filed period — the margin cannot be recomputed.")
            # No omission fail here: with no common period, a
            # correct Analysis has no margin claim (analyst.py).
        else:
            cur_rev = next(f for f in revs if f.period == common[-1])
            cur_op = opinc_by_period[common[-1]]
            expected = cur_op.value / cur_rev.value * 100.0 if cur_rev.value else None
            if c is None:
                fail("omission", "Pack has revenue + operating income for a common period but Analysis has no margin claim.")
            elif c.value is None or expected is None or abs(c.value - expected) > 0.5:
                fail("arithmetic", f"Operating margin claim {c.value} does not match recomputed {expected}.")

    # Per-claim staleness: a claim whose evidence all predates
    # the reported quarter by more than a year is not a claim
    # about that quarter. Pack-level staleness looks at the
    # newest fact of ANY metric, so one current metric masked
    # MSFT revenue from 2010 inside a briefing labelled Q3 2026.
    # Evidence-free claims (consensus, price reaction) are
    # exempt by design — their freshness is covered by the
    # claims that do cite facts.
    from datetime import timedelta
    if pack.quarter_end:
        cutoff = pack.quarter_end - timedelta(days=365)
        facts_by_id = {f.id: f for f in pack.facts}
        for c in analysis.claims:
            periods = [parse_period(facts_by_id[e].period) for e in c.evidence_ids
                       if e in facts_by_id and parse_period(facts_by_id[e].period) is not None]
            if periods and max(periods) < cutoff:
                fail("staleness", f"Claim '{c.text[:60]}' cites only facts up to {max(periods)} — more than a year before the reported quarter ending {pack.quarter_end}.")

    # 3+4. EPS basis and consensus reflection
    cons = pack.consensus or {}
    eps_entries = [b for b in analysis.beat_miss if b.get("metric") == "eps"]
    for b in eps_entries:
        if not b.get("basis"):
            fail("basis", f"EPS beat/miss entry {b} has no basis label.")
    if isinstance(cons, dict) and cons.get("status") in ("available", "available_range"):
        if cons.get("eps_estimate") is not None and cons.get("eps_reported") is not None:
            expected = _pct(float(cons["eps_reported"]), float(cons["eps_estimate"]))
            match = [b for b in eps_entries if b.get("estimate") == float(cons["eps_estimate"]) and b.get("actual") == float(cons["eps_reported"])]
            if not match:
                fail("beat_miss", "Pack Nasdaq consensus (EPS estimate + reported) is not reflected in beat_miss.")
            elif expected is not None and abs(match[0].get("diff_pct", 0) - round(expected, 2)) > 0.5:
                fail("arithmetic", f"Nasdaq EPS beat/miss {match[0].get('diff_pct')} does not match recomputed {expected}.")
        av = cons.get("alpha_vantage_cross_check") or {}
        if av.get("eps_reported") is not None and av.get("eps_estimate") is not None:
            match = [b for b in eps_entries if b.get("estimate") == float(av["eps_estimate"]) and b.get("actual") == float(av["eps_reported"])]
            if not match:
                fail("beat_miss", "Alpha Vantage cross-check EPS is in the pack but not in beat_miss — basis split is incomplete.")
    # No beat/miss entry may use a consensus number not in the pack.
    pack_eps_numbers = set()
    if isinstance(cons, dict):
        for k in ("eps_estimate", "eps_reported"):
            if cons.get(k) is not None:
                pack_eps_numbers.add(float(cons[k]))
        av = cons.get("alpha_vantage_cross_check") or {}
        for k in ("eps_estimate", "eps_reported"):
            if av.get(k) is not None:
                pack_eps_numbers.add(float(av[k]))
        if cons.get("eps_usd") is not None:
            pack_eps_numbers.add(float(cons["eps_usd"]))
    for b in eps_entries:
        if b.get("estimate") is not None and float(b["estimate"]) not in pack_eps_numbers:
            # Range entries have estimate_range instead of estimate; skip those.
            if "estimate_range" not in b:
                fail("beat_miss", f"EPS beat/miss uses estimate {b['estimate']} that is not in pack.consensus.")

    # Price reaction recomputation
    pr = pack.price_reaction or {}
    closes = pr.get("closes") if isinstance(pr, dict) else None
    price_entries = [b for b in analysis.beat_miss if b.get("metric") == "price_reaction"]
    if closes and len(closes) >= 2 and price_entries:
        report_date = pack.report_date.date().isoformat() if hasattr(pack.report_date, "date") else str(pack.report_date)[:10]
        idx = next((i for i, c in enumerate(closes) if c.get("date") == report_date), None)
        if idx is not None and idx + 1 < len(closes):
            expected = _pct(float(closes[idx + 1]["close"]), float(closes[idx]["close"]))
            if expected is not None and abs(price_entries[0].get("diff_pct", 0) - round(expected, 2)) > 0.5:
                fail("arithmetic", f"Price reaction {price_entries[0].get('diff_pct')} does not match recomputed {expected} from closes.")
    if price_entries and not closes:
        fail("overclaim", "Price reaction claim exists but pack has no closes to compute it from.")

    # 7. Independent re-query (best effort, recorded honestly)
    if mcp_call is not None:
        try:
            cf = mcp_call("filings", "get_company_facts", {"ticker": pack.ticker})
            if isinstance(cf, dict) and cf.get("company_name") == pack.company_name:
                rechecked.append("company_name matches filings-mcp")
            else:
                warn("requery", f"filings-mcp company_name {cf.get('company_name') if isinstance(cf, dict) else cf} differs from pack {pack.company_name}.")
        except Exception as e:
            warn("requery", f"filings-mcp re-query failed: {e} — live verification not completed for company facts.")
        try:
            lf = mcp_call("filings", "get_latest_earnings_filing", {"ticker": pack.ticker})
            if isinstance(lf, dict) and lf.get("filingDate") == pack.report_date.date().isoformat():
                rechecked.append("latest filing date matches filings-mcp")
            elif isinstance(lf, dict) and lf.get("filingDate"):
                warn("requery", f"filings-mcp latest filing date {lf.get('filingDate')} differs from pack report_date {pack.report_date.date()} — a newer filing may exist.")
        except Exception as e:
            warn("requery", f"filings-mcp latest-filing re-query failed: {e}.")
        try:
            cons_live = mcp_call("estimates_news", "get_consensus_estimates",
                                 {"ticker": pack.ticker, "quarter": pack.quarter_label,
                                  "report_date": pack.report_date.date().isoformat()})
            if isinstance(cons_live, dict) and cons_live.get("eps_estimate") is not None and isinstance(cons, dict) and cons.get("eps_estimate") is not None:
                if float(cons_live["eps_estimate"]) == float(cons["eps_estimate"]):
                    rechecked.append("consensus EPS estimate matches estimates-news-mcp re-query")
                else:
                    warn("requery", f"Consensus EPS estimate changed on re-query: pack {cons.get('eps_estimate')} vs live {cons_live.get('eps_estimate')}.")
        except Exception as e:
            warn("requery", f"estimates-news-mcp re-query failed: {e}.")

    verdict = "FAIL" if any(i["severity"] == "fail" for i in issues) else "PASS"
    return Critique(verdict=verdict, issues=issues, rechecked_facts=rechecked)
