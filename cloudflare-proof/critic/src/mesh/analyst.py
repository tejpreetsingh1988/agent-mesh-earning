"""Analyst — computes only from the EvidencePack, with derivations.

Fixed Oct 29 after the live AMZN run exposed a real bug: the old
Analyst took the last two facts for a metric, whatever their gap,
and called the change "YoY". For AMZN that turned Q4 2025 -> Q1 2026
(a QoQ move of -14.9%) into a fake YoY claim, and presented Q1 2026
numbers as if they were the just-reported Q3 2026 quarter.

Rules now, enforced here and re-checked by Critic:
- YoY = two facts exactly 12 months apart (same month, year +/- 1).
  QoQ = two facts exactly 3 months apart. Any other gap gets NO
  growth claim — a gap of 6 or 9 months is neither, and is not
  silently relabelled.
- Every growth claim names its periods, e.g.
  "Revenue YoY growth (2025-09-30 -> 2026-09-30)".
- If the pack has no fact for its quarter_end, Analyst does NOT
  present an earlier quarter's growth as the reported quarter's.
  It says so, and reports the latest available quarter's growth
  with that quarter's period named.
- EPS beat/miss is per basis (see Oct 29 GOOGL finding), and only
  if reported EPS is present. A forecast-only consensus (Nasdaq row
  with a forecast but no reported EPS yet, as AMZN had on Oct 29)
  produces no beat/miss — it produces a note that beat/miss cannot
  be computed yet.
- Verdict wording uses up/down, never "up -14.9%".
- Drivers use outperform/underperform, never "grew faster" when
  both numbers are falling.
- Claim display values are rounded (USD_B to 1 decimal, USD to 2)
  so the UI does not show 213.386000000-style artefacts.
"""
import calendar
import re
from datetime import date

from .schemas import Analysis, Claim, EvidencePack

_QUARTER_MONTHS = {"Q1": 3, "Q2": 6, "Q3": 9, "Q4": 12}


def parse_period(period: str) -> date | None:
    """Parse a fact period into a date: ISO date, or 'Q3 2026'."""
    try:
        return date.fromisoformat(period)
    except ValueError:
        pass
    m = re.match(r"(Q[1-4])\s+(\d{4})", period or "")
    if m:
        month = _QUARTER_MONTHS[m.group(1)]
        return date(int(m.group(2)), month, calendar.monthrange(int(m.group(2)), month)[1])
    return None


def _months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def _pct(new: float, old: float) -> float | None:
    if not old:
        return None
    return (new - old) / abs(old) * 100.0


def _fmt(value: float, unit: str) -> str:
    if unit == "USD_B":
        return f"${value:.1f}B"
    if unit == "USD":
        return f"${value:.2f}"
    if unit == "shares_B":
        return f"{value:.2f}B shares"
    return f"{value:.2f}"


def _by_metric(pack: EvidencePack, metric: str):
    out = []
    for f in pack.facts:
        if f.metric == metric:
            d = parse_period(f.period)
            if d is not None:
                out.append((d, f))
    out.sort(key=lambda x: x[0])
    return out


def _pair(fs, months: int):
    """Latest (prev, cur) pair in fs exactly `months` apart, or None."""
    for i in range(len(fs) - 1, 0, -1):
        cur_d, cur = fs[i]
        for j in range(i - 1, -1, -1):
            prev_d, prev = fs[j]
            gap = _months_between(prev_d, cur_d)
            if gap == months:
                return prev, cur
            if gap > months:
                # Earlier prevs are even further away.
                break
    return None


def analyse(pack: EvidencePack) -> Analysis:
    if pack.status != "REPORTED":
        return Analysis(
            ticker=pack.ticker, quarter_label=pack.quarter_label,
            verdict_draft="NOT_REPORTED_YET: no reported quarter in the EvidencePack, so no analysis is possible.",
            claims=[], beat_miss=[],
            drivers=[], risks_and_watch=["No reported quarter in EvidencePack — do not present any earnings numbers for this ticker."],
        )

    claims: list[Claim] = []
    beat_miss: list[dict] = []
    drivers: list[str] = []
    risks: list[str] = list(pack.missing)

    def add_claim(text: str, value: float | None, derivation: str, ids: list[str]):
        claims.append(Claim(text=text, value=value, derivation=derivation, evidence_ids=ids))

    growth: dict[str, dict[str, float]] = {}  # metric -> {"yoy": x, "qoq": y}

    # --- Growth: YoY (12m) and QoQ (3m), latest pair each, periods named ---
    for metric, label in [("total_revenue", "Revenue"), ("operating_income", "Operating income"),
                          ("net_income", "Net income"), ("ebitda", "EBITDA"),
                          ("operating_cash_flow", "Operating cash flow"),
                          ("free_cash_flow", "Free cash flow"),
                          ("cash_and_equivalents", "Cash and equivalents"),
                          ("short_term_investments", "Short-term investments"),
                          ("cash_and_st_investments", "Cash and short-term investments"),
                          ("buybacks", "Buybacks"),
                          ("shares_outstanding", "Shares outstanding"),
                          ("cloud_revenue", "Cloud revenue"), ("gaap_eps", "GAAP EPS")]:
        fs = _by_metric(pack, metric)
        growth[metric] = {}
        for months, kind in [(12, "YoY"), (3, "QoQ")]:
            pair = _pair(fs, months)
            if pair is None:
                continue
            prev, cur = pair
            pct = _pct(cur.value, prev.value)
            if pct is None:
                continue
            growth[metric][kind.lower()] = pct
            add_claim(
                f"{label} {kind} growth ({prev.period} -> {cur.period}): {pct:+.1f}% ({_fmt(prev.value, prev.unit)} -> {_fmt(cur.value, cur.unit)})",
                pct, f"({cur.value} - {prev.value}) / |{prev.value}| * 100, from facts {cur.id} and {prev.id}.",
                [cur.id, prev.id])

    # If the pack's quarter_end has no fact at all, say so plainly.
    qe = pack.quarter_end
    has_qe_fact = any(parse_period(f.period) == qe for f in pack.facts)
    if pack.facts and not has_qe_fact and not any("No fact in this pack is for the reported quarter" in r for r in risks):
        latest_period = max((parse_period(f.period) for f in pack.facts if parse_period(f.period) is not None), default=None)
        risks.append(
            f"No fact in this pack is for the reported quarter ending {qe} — the latest fact period is {latest_period}. "
            "Growth claims above are for that latest available period, named in each claim, not for the reported quarter. "
            "Do not present them as the reported quarter's results.")

    # --- Margins: only a period where BOTH revenue and operating
    # income are filed. The old code fell back to the latest
    # operating income of ANY period when the latest revenue
    # period had none — that is how MSFT got a 230.1% margin
    # (2026 operating income divided by 2010 revenue). No common
    # period means no margin claim, stated in risks, never a
    # margin across different periods.
    revs = _by_metric(pack, "total_revenue")
    opincs = _by_metric(pack, "operating_income")
    rev_by_period = {d: f for d, f in revs}
    opinc_by_period = {d: f for d, f in opincs}
    common = sorted(set(rev_by_period) & set(opinc_by_period))
    if common:
        cur_rev, cur_op = rev_by_period[common[-1]], opinc_by_period[common[-1]]
        if cur_rev.value:
            margin = cur_op.value / cur_rev.value * 100.0
            add_claim(f"Operating margin ({cur_rev.period}): {margin:.1f}% ({_fmt(cur_op.value, cur_op.unit)} / {_fmt(cur_rev.value, cur_rev.unit)})",
                      margin, f"{cur_op.value} / {cur_rev.value} * 100, from facts {cur_op.id} and {cur_rev.id}.",
                      [cur_op.id, cur_rev.id])
    elif revs and opincs:
        risks.append("Revenue and operating income have no common filed period — no operating-margin claim (a margin across different periods would be meaningless).")

    # --- CapEx vs operating income (latest common period, if both present) ---
    capex = _by_metric(pack, "capex")
    if capex and opincs:
        cap_by_period = {d: f for d, f in capex}
        common_cap = sorted(set(cap_by_period) & set(opinc_by_period))
        if common_cap:
            cur_cap, cur_op = cap_by_period[common_cap[-1]], opinc_by_period[common_cap[-1]]
            if cur_cap.value > cur_op.value:
                risks.append(f"CapEx ({_fmt(cur_cap.value, cur_cap.unit)}) exceeded operating income ({_fmt(cur_op.value, cur_op.unit)}) in {cur_cap.period} — cash-flow watch, not a verdict on its own.")

    # --- Beat/miss: revenue ---
    cons = pack.consensus or {}
    if revs and isinstance(cons, dict):
        cur_rev = revs[-1][1]
        if cons.get("revenue_usd_b") is not None:
            est = float(cons["revenue_usd_b"])
            diff = _pct(cur_rev.value, est)
            if diff is not None:
                beat_miss.append({"metric": "revenue", "actual": cur_rev.value, "estimate": est,
                                  "diff_pct": round(diff, 2), "basis": "single estimate from pack.consensus"})
                add_claim(f"Revenue vs consensus: {diff:+.1f}% ({_fmt(cur_rev.value, cur_rev.unit)} vs ${_fmt(est, 'USD_B')[1:]})",
                          diff, f"({cur_rev.value} - {est}) / {est} * 100, consensus from pack.consensus.", [cur_rev.id])
        elif cons.get("revenue_estimate_low_b") is not None and cons.get("revenue_estimate_high_b") is not None:
            lo, hi = float(cons["revenue_estimate_low_b"]), float(cons["revenue_estimate_high_b"])
            pos = "within" if lo <= cur_rev.value <= hi else ("below" if cur_rev.value < lo else "above")
            beat_miss.append({"metric": "revenue", "actual": cur_rev.value, "estimate_range_b": [lo, hi],
                              "position": pos, "basis": "range, not a single estimate — do not quote a single beat/miss %"})
            add_claim(f"Revenue vs consensus range: {pos} the ${lo:.2f}B-${hi:.2f}B range ({_fmt(cur_rev.value, cur_rev.unit)})",
                      None, f"Actual {cur_rev.value} compared to range [{lo}, {hi}] from pack.consensus.", [cur_rev.id])

    # --- Beat/miss: EPS, per basis, only if reported is present ---
    def eps_entry(reported, estimate, basis_label):
        if reported is None or estimate is None:
            return
        diff = _pct(reported, estimate)
        if diff is None:
            return
        beat_miss.append({"metric": "eps", "actual": reported, "estimate": estimate,
                          "diff_pct": round(diff, 2), "basis": basis_label})
        add_claim(f"EPS vs consensus ({basis_label}): {diff:+.1f}% (${reported:.2f} vs ${estimate:.2f})",
                  diff, f"({reported} - {estimate}) / {estimate} * 100, {basis_label}.", [])

    if isinstance(cons, dict):
        if cons.get("status") == "forecast_only" and not any("forecast-only" in r for r in risks):
            risks.append(
                f"Consensus forecast available (EPS ${cons.get('eps_estimate')} from {cons.get('num_estimates')} estimates) "
                "but reported EPS is not yet in the consensus source — beat/miss cannot be computed yet. Do not quote a miss.")
        if cons.get("eps_reported") is not None and cons.get("eps_estimate") is not None:
            eps_entry(float(cons["eps_reported"]), float(cons["eps_estimate"]),
                      "Nasdaq: GAAP reported vs consensus forecast (forecast basis unstated — not a clean adjusted miss)")
        av = cons.get("alpha_vantage_cross_check") or {}
        if av.get("eps_reported") is not None and av.get("eps_estimate") is not None:
            eps_entry(float(av["eps_reported"]), float(av["eps_estimate"]),
                      "Alpha Vantage cross-check: adjusted reported vs Alpha Vantage estimate")
        if cons.get("eps_usd") is not None and _by_metric(pack, "gaap_eps"):
            if not any(b.get("metric") == "eps" for b in beat_miss):
                eps_entry(float(_by_metric(pack, "gaap_eps")[-1][1].value), float(cons["eps_usd"]),
                          "pack.consensus.eps_usd (basis as labelled in pack.consensus)")
        if cons.get("eps_estimate_low") is not None and cons.get("eps_estimate_high") is not None:
            gaaps = _by_metric(pack, "gaap_eps")
            if gaaps:
                lo, hi = float(cons["eps_estimate_low"]), float(cons["eps_estimate_high"])
                actual = gaaps[-1][1].value
                pos = "within" if lo <= actual <= hi else ("below" if actual < lo else "above")
                beat_miss.append({"metric": "eps", "actual": actual, "estimate_range": [lo, hi],
                                  "position": pos, "basis": "range — GAAP actual vs adjusted-leaning range, label the basis gap"})
                add_claim(f"GAAP EPS vs consensus range: {pos} the {lo}-{hi} range (${actual:.2f}) — basis gap applies",
                          None, f"Actual {actual} compared to range [{lo}, {hi}].", [gaaps[-1][1].id])

    # --- Price reaction from closes only ---
    pr = pack.price_reaction or {}
    closes = pr.get("closes") if isinstance(pr, dict) else None
    if closes:
        report_date = pack.report_date.date().isoformat() if hasattr(pack.report_date, "date") else str(pack.report_date)[:10]
        # Base = last trading-day close on or before the report
        # date; reaction = first trading-day close after it. The
        # old exact-match rule silently produced nothing when
        # the report date was a weekend or holiday (no close
        # row for that date) — the "next row after report date"
        # rule skips weekends/holidays by construction.
        ordered = sorted((c for c in closes if c.get("date")), key=lambda c: c["date"])
        prev = next((c for c in reversed(ordered) if c["date"] <= report_date), None)
        cur = next((c for c in ordered if c["date"] > report_date), None)
        if prev is not None and cur is not None:
            pct = _pct(float(cur["close"]), float(prev["close"]))
            if pct is not None:
                add_claim(f"Regular-session close change ({prev['date']} -> {cur['date']}): {pct:+.1f}% (${float(prev['close']):.2f} -> ${float(cur['close']):.2f})",
                          pct, f"({cur['close']} - {prev['close']}) / {prev['close']} * 100, regular-session closes from price_reaction. NOT an after-hours move.",
                          [])
                beat_miss.append({"metric": "price_reaction", "window": f"{prev['date']} -> {cur['date']}",
                                  "diff_pct": round(pct, 2), "basis": "regular-session closes only"})
        elif prev is not None and cur is None:
            risks.append("No trading-day close after the report date yet in price_reaction — market reaction cannot be computed yet, and no after-hours move is claimed.")
        elif prev is None:
            risks.append("No trading-day close on or before the report date in price_reaction — market reaction cannot be computed yet.")
    elif isinstance(pr, dict) and pr.get("after_hours_move_pct") is not None and not closes:
        risks.append("Pack price_reaction has an after-hours percentage but no underlying closes — Analyst cannot verify it and does not use it as a market-reaction claim.")

    # --- Drivers, from growth only, sign-agnostic wording ---
    rev_g = growth.get("total_revenue", {})
    op_g = growth.get("operating_income", {})
    cloud_g = growth.get("cloud_revenue", {})
    if cloud_g.get("yoy") is not None and rev_g.get("yoy") is not None:
        if cloud_g["yoy"] > rev_g["yoy"]:
            drivers.append("Cloud outperformed total revenue on YoY growth (see YoY claims).")
        elif cloud_g["yoy"] < rev_g["yoy"]:
            drivers.append("Cloud underperformed total revenue on YoY growth (see YoY claims).")
    if op_g.get("yoy") is not None and rev_g.get("yoy") is not None:
        if op_g["yoy"] > rev_g["yoy"]:
            drivers.append("Operating income outperformed revenue on YoY growth, implying margin expansion (see margin claim).")
        elif op_g["yoy"] < rev_g["yoy"]:
            drivers.append("Operating income underperformed revenue on YoY growth, implying margin compression (see margin claim).")

    def _up_down(pct: float) -> str:
        return f"up {pct:.1f}%" if pct >= 0 else f"down {abs(pct):.1f}%"

    verdict_parts = []
    if rev_g.get("yoy") is not None:
        verdict_parts.append(f"Revenue {_up_down(rev_g['yoy'])} YoY")
    elif rev_g.get("qoq") is not None:
        verdict_parts.append(f"Revenue {_up_down(rev_g['qoq'])} QoQ (latest available period — see claims)")
    margin_claims = [c for c in claims if c.text.startswith("Operating margin")]
    if margin_claims:
        verdict_parts.append(f"operating margin {margin_claims[0].value:.1f}%")
    eps_entries = [b for b in beat_miss if b.get("metric") == "eps"]
    if eps_entries:
        e = eps_entries[0]
        verdict_parts.append(f"EPS {e['diff_pct']:+.1f}% vs consensus ({e['basis']})")
    verdict_draft = "; ".join(verdict_parts) + "." if verdict_parts else "Insufficient evidence in the pack to draft a verdict — see claims and risks."

    return Analysis(ticker=pack.ticker, quarter_label=pack.quarter_label,
                    verdict_draft=verdict_draft, claims=claims, beat_miss=beat_miss,
                    drivers=drivers, risks_and_watch=risks)
