"""Deterministic facts from an earnings-release exhibit (6-K path).

Foreign private issuers (Nebius, etc.) file 6-K, not 10-Q, so
there is no XBRL series for the Scout's EDGAR overlay to read.
Their results press release (exhibit 99.1 to the 6-K) still
states the quarter in a Financial Highlights table:

    Revenues                    146.1   980.8   571%   302.1  1,962.1  549%
    Adjusted EBITDA / (loss)    (5.2)   465.8   n/m    (79.9)  831.5   n/m
    Net income / (loss) ...     (119.6) (37.5)  -69%   278.6   393.3   41%

Each row is (prior quarter, current quarter, change%, prior
nine-months, current nine-months, change%) in $ millions. This
module parses those rows deterministically — no LLM — and emits
EvidencePack-shaped facts for the current and prior-year
quarters, plus the shares-outstanding line when the release
states it.

Every row is self-checked against its own stated change%:
|(cur - prev) / |prev| * 100 - stated%| <= 1.5, or the change
is "n/m" with a loss/sign-flip base. A row that fails the check
is skipped with a note in `missing`, never guessed. Facts are
labelled "SEC EDGAR (6-K exhibit 99.1 — release text)" so the
briefing never presents them as XBRL.
"""
from __future__ import annotations

import re
from datetime import date

# (label as printed in the release, metric, display label)
RELEASE_METRICS: list[tuple[str, str]] = [
    ("Revenues", "total_revenue"),
    ("Net income / (loss) from continuing operations", "net_income"),
    ("Adjusted EBITDA / (loss)", "adjusted_ebitda"),
    ("Adjusted net income / (loss)", "adjusted_net_income"),
]

_PUBLISHER = "SEC EDGAR (6-K exhibit 99.1 — release text)"

# One token in a highlights row: a parenthesised negative, a plain
# number (optionally followed by %), or n/m. The digit class must
# start with a digit: a bare "," (as in "amortization, (2)") must
# never tokenize as a number.
_TOKEN_RE = re.compile(
    r"\(\s*(\d[\d,]*(?:\.\d+)?)\s*\)"      # (37.5) -> negative value
    r"|(-?\d[\d,]*(?:\.\d+)?)\s*(%)?"      # 980.8 | -69 % | 571 %
    r"|(n/m)",
    re.IGNORECASE,
)

_SHARES_RE = re.compile(
    r"shares issued and outstanding as of [A-Za-z]+\s+\d{1,2},\s+\d{4}\s+was\s+([\d,]+)",
    re.IGNORECASE,
)

# "for the three and nine months ended September 30, 2026" —
# the release states its own period end; 6-K submissions carry
# no period-end reportDate (it is the filing date), so the
# Scout reads the quarter end from the release itself.
_QUARTER_END_RE = re.compile(
    r"(?:three and nine months|three months|nine months|quarter)"
    r"\s+ended\s+([A-Za-z]+\s+\d{1,2},\s*\d{4})",
    re.IGNORECASE,
)

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june",
     "july", "august", "september", "october", "november", "december"])}


def quarter_end_from_release(clean_text: str) -> date | None:
    """The quarter end a results release states for itself, or
    None when it cannot be read."""
    m = _QUARTER_END_RE.search(clean_text or "")
    if not m:
        return None
    try:
        month_s, rest = m.group(1).split(None, 1)
        day_s, year_s = rest.replace(",", "").split()
        return date(int(year_s), _MONTHS[month_s.lower()], int(day_s))
    except (ValueError, KeyError):
        return None

_MAX_LABEL_OCCURRENCES = 5
_TOKENS_AFTER_LABEL = 200  # chars of text to scan for the row


def _label_re(label: str) -> re.Pattern:
    # Flexible whitespace: the cleaned text collapses runs of
    # spaces, but the label's own spaces may be nbsp in source.
    # Anchored to a line start: an unanchored "Revenues" also
    # matches inside "Cost of revenues" (whose row self-checks
    # fine at 412%) and would emit cost figures as revenue.
    parts = [re.escape(p) for p in label.split(" ")]
    return re.compile(r"(?m)^\s*" + r"\s+".join(parts), re.IGNORECASE)


def _tokens(text: str) -> list[tuple[str, float | None]]:
    """(kind, value) tokens: kind is 'val', 'pct', or 'nm'."""
    out: list[tuple[str, float | None]] = []
    for m in _TOKEN_RE.finditer(text):
        if m.group(4) is not None:
            out.append(("nm", None))
        elif m.group(1) is not None:
            out.append(("val", -float(m.group(1).replace(",", ""))))
        else:
            v = float(m.group(2).replace(",", ""))
            out.append(("pct", v) if m.group(3) else ("val", v))
    return out


def _parse_row(tokens: list[tuple[str, float | None]]) -> dict | None:
    """(prior_q, cur_q) in $ millions, or None when the row does
    not match the (val, val, pct|nm, val, val, pct|nm) shape or
    fails its own stated-change self-check."""
    if len(tokens) < 6:
        return None
    t = tokens[:6]
    if not all(k == "val" for k, _ in (t[0], t[1], t[3], t[4])):
        return None
    if t[2][0] not in ("pct", "nm") or t[5][0] not in ("pct", "nm"):
        return None
    prev_q, cur_q = t[0][1], t[1][1]
    if prev_q is None or cur_q is None:
        return None
    if t[2][0] == "pct":
        stated = t[2][1]
        if prev_q == 0 or stated is None:
            return None
        # The release's change% may use either convention on a
        # negative base: (cur-prev)/|prev| (the Analyst's) or
        # (cur-prev)/prev (the release's "loss down 69%" reading).
        # Accept the row when either matches the stated figure.
        computed_abs = (cur_q - prev_q) / abs(prev_q) * 100
        computed_signed = (cur_q - prev_q) / prev_q * 100
        if min(abs(computed_abs - stated), abs(computed_signed - stated)) > 1.5:
            return None
    else:
        # n/m is only meaningful on a loss / sign-flip base.
        if prev_q > 0 and cur_q > 0:
            return None
    return {"prior_q": prev_q, "cur_q": cur_q}


def _prior_year(d: date) -> date:
    try:
        return d.replace(year=d.year - 1)
    except ValueError:  # Feb 29 -> Feb 28
        return d.replace(year=d.year - 1, day=28)


def extract_release_facts(clean_text: str, *, ticker: str, quarter_end: date,
                          exhibit_url: str, filing_date: str) -> dict:
    """Facts from a results press release's highlights table.

    Returns {"facts": [...], "missing": [...]} in the shape the
    Scout's get_filing_facts leg returns (dicts, not Fact
    objects — the Scout builds the Fact + SourceRef itself).
    Values are USD_B (the release states $ millions).
    """
    facts: list[dict] = []
    missing: list[str] = []
    text = clean_text or ""
    cur_period = quarter_end.isoformat()
    prev_period = _prior_year(quarter_end).isoformat()

    for label, metric in RELEASE_METRICS:
        found = None
        for m in list(_label_re(label).finditer(text))[:_MAX_LABEL_OCCURRENCES]:
            row = _parse_row(_tokens(text[m.end():m.end() + _TOKENS_AFTER_LABEL]))
            if row is not None:
                found = row
                break
        if found is None:
            missing.append(
                f"Release-text parse: could not verify the '{label}' row "
                f"against its stated change% — no {metric} fact emitted.")
            continue
        for period, value_m in ((prev_period, found["prior_q"]), (cur_period, found["cur_q"])):
            facts.append({
                "id": f"release_{metric}_{period}",
                "metric": metric,
                "value": round(value_m / 1000, 6),
                "unit": "USD_B",
                "period": period,
                "source_tag": label,
                "derived": False,
                "derivation": "",
                "form": "6-K",
                "filed": filing_date,
                "publisher": _PUBLISHER,
                "url": exhibit_url,
            })

    shares_m = _SHARES_RE.search(text)
    if shares_m:
        facts.append({
            "id": f"release_shares_outstanding_{cur_period}",
            "metric": "shares_outstanding",
            "value": float(shares_m.group(1).replace(",", "")),
            "unit": "shares",
            "period": cur_period,
            "source_tag": "Shares issued and outstanding",
            "derived": False,
            "derivation": "",
            "form": "6-K",
            "filed": filing_date,
            "publisher": _PUBLISHER,
            "url": exhibit_url,
        })

    return {"facts": facts, "missing": missing, "ticker": ticker}
