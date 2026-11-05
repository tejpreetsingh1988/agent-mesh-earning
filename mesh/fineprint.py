"""Fine print (Batch 30): what's new or changed in this quarter's
filings vs last quarter's, surfaced by one LLM pass.

Sources: this quarter's 10-Q and last quarter's 10-Q (MD&A +
footnotes, diffed paragraph by paragraph) plus the quarter's
8-K exhibit 99.1 release highlights. The LLM picks up to 5
items a reader would most want to know.

Framing rules (binding): the section is LLM-surfaced, NOT
Critic-verified, and never enters the verified claims table.
Every number shown must appear verbatim in the fetched filing
text (same validator rule as the story); every quote must
appear verbatim (normalized) in the text. An item failing
either check is dropped, never patched. No model at all (or
every model failing) is a valid hiding result — the section
simply doesn't render.
"""
import asyncio
import difflib
import json
import re

from .kpi import (EDGAR_HEADERS, _call_openrouter_async,
                  fetch_release_text_async, fetch_release_text_sync,
                  strip_html)
from .llm import MODELS, _call_openrouter
from .gateway_binding import GATEWAY_TIMEOUT_S, call_gateway_binding
from .worker_ai import WORKERS_AI_MODEL, WORKERS_AI_TIMEOUT_S, call_workers_ai
from .worker_http import fetch_json as _afetch_json
from .worker_http import fetch_text as _afetch_text

MAX_PASSAGES = 12
MAX_ITEMS = 5
SECTION_CAP = 60000
MIN_PARA_CHARS = 60

# Passages touching these get ranked first: the unusually
# specific items (litigation, impairments, restatements,
# covenant trouble) are the fine print that matters.
KEYWORD_RE = re.compile(
    r"litigat|impairment|restat|investigat|contingen|guarantee|"
    r"covenant|default|material weakness|write-down|write-off|"
    r"discontinu|settlement|penalt|fraud|going concern|substantial doubt",
    re.IGNORECASE)

MDA_RE = re.compile(r"management's discussion and analysis", re.IGNORECASE)
NOTES_RE = re.compile(
    r"notes to (condensed )?consolidated financial statements|"
    r"notes to financial statements", re.IGNORECASE)
ITEM_RE = re.compile(r"^item\s+\d+[a-z]?\b", re.IGNORECASE)
NUMBER_RE = re.compile(r"\d[\d,]*\.?\d*")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def extract_sections(text: str) -> dict:
    """MD&A + footnotes from a stripped 10-Q, each capped. A
    heading starts its section; the next top-level ITEM heading
    ends it. A missing heading yields an empty section (the
    diff just uses what's found) — filers vary too much to
    fail on it."""
    out = {"mda": "", "notes": ""}
    if not text:
        return out
    lines = text.splitlines()
    starts = {}
    for i, line in enumerate(lines):
        s = line.strip()
        if "mda" not in starts and MDA_RE.search(s):
            starts["mda"] = i
        if "notes" not in starts and NOTES_RE.search(s):
            starts["notes"] = i
    for key, start in starts.items():
        end = len(lines)
        for j in range(start + 1, len(lines)):
            if ITEM_RE.match(lines[j].strip()):
                end = j
                break
        out[key] = "\n".join(lines[start:end])[:SECTION_CAP]
    return out


def split_paragraphs(text: str) -> list[str]:
    """Sentence-level passages. Stripped 10-Q text has no blank
    lines (strip_html collapses them), so paragraphs cannot be
    recovered from whitespace — sentences are the unit instead.
    Split on sentence-ending punctuation followed by a capital,
    digit or quote; fragments under MIN_PARA_CHARS (headers,
    table shards, split abbreviations) are dropped."""
    paras = []
    for chunk in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])", text or ""):
        p = re.sub(r"\s+", " ", chunk).strip()
        if len(p) >= MIN_PARA_CHARS:
            paras.append(p)
    return paras


def diff_paragraphs(cur: list[str], prev: list[str]) -> tuple[list[str], list[str]]:
    """(new, changed) vs last quarter's sentences. Exact
    normalized match = unchanged; a close match (difflib >= 0.8)
    = changed; anything else = new."""
    prev_norm = {_norm(p): p for p in prev}
    prev_norm_list = list(prev_norm)
    new, changed = [], []
    for p in cur:
        n = _norm(p)
        if n in prev_norm:
            continue
        close = difflib.get_close_matches(n, prev_norm_list, n=1, cutoff=0.8)
        if close:
            changed.append(p)
        else:
            new.append(p)
    return new, changed


def rank_passages(new: list[str], changed: list[str]) -> list[dict]:
    """New+keyword first, then new, then changed+keyword, then
    changed; capped at MAX_PASSAGES. Each passage carries its
    kind so the prompt can label it."""
    def keyed(paras, kind):
        return [{"text": p, "kind": kind, "keyword": bool(KEYWORD_RE.search(p))} for p in paras]

    ranked = (sorted(keyed(new, "new"), key=lambda d: (not d["keyword"], -len(d["text"])))
              + sorted(keyed(changed, "changed"), key=lambda d: (not d["keyword"], -len(d["text"]))))
    # New first regardless of keyword: a brand-new passage
    # outranks a merely edited one.
    ranked = sorted(ranked, key=lambda d: (d["kind"] != "new", not d["keyword"]))
    return ranked[:MAX_PASSAGES]


def fineprint_prompt(passages: list[dict], release_head: str, quarter_label: str) -> tuple:
    system = ("You surface fine print from earnings filings. You never invent numbers, "
              "never paraphrase a number into a different one, and never write a number "
              "that does not appear in the passages given.")
    body = [f"Quarter: {quarter_label}",
            "NEW OR CHANGED passages from this quarter's 10-Q vs last quarter's (MD&A and footnotes):"]
    for i, p in enumerate(passages, 1):
        tag = p.get("section", "") or "10-Q"
        body.append(f"[{i} {p['kind'].upper()} {tag}] {p['text']}")
    if release_head:
        body.append("This quarter's earnings release (exhibit 99.1) opening, for context only:")
        body.append(release_head[:4000])
    body.append(
        "Pick up to 5 items a reader would most want to know — new risks, changed language, "
        "unusually specific disclosures. For each: section (\"MD&A\", \"Notes\", or \"Release\"), "
        "quote (a verbatim substring of a passage above, at most 300 characters), and "
        "why_it_matters (one sentence, using no numbers except ones inside the quote). "
        "Return JSON only: {\"items\": [{\"section\": ..., \"quote\": ..., \"why_it_matters\": ...}]}. "
        "If nothing is worth surfacing, return {\"items\": []}.")
    return system, "\n\n".join(body)


def parse_fineprint_json(text: str) -> tuple[list[dict], bool]:
    """(items, parsed_ok): fences tolerated, 'items' key required.
    parsed_ok False = garbled reply (try the next model)."""
    if not text:
        return [], False
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        body = json.loads(raw)
    except (ValueError, TypeError):
        return [], False
    items = body.get("items") if isinstance(body, dict) else None
    if not isinstance(items, list):
        return [], False
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        section = str(it.get("section", "") or "").strip()
        quote = str(it.get("quote", "") or "").strip()
        why = str(it.get("why_it_matters", "") or "").strip()
        if section and quote and why:
            out.append({"section": section, "quote": quote, "why_it_matters": why})
    return out, True


def validate_fineprint(items: list[dict], full_text: str) -> list[dict]:
    """Drop (never patch) any item whose quote is not verbatim
    (normalized) in the fetched text, or whose why_it_matters
    carries a number that does not appear (digit-normalized) in
    the text. The quote's own numbers are safe by construction.
    Capped at MAX_ITEMS."""
    norm_full = _norm(full_text)
    digits_full = re.sub(r"[^0-9]", "", norm_full)
    out = []
    for it in items:
        if _norm(it["quote"]) not in norm_full:
            continue
        bad = False
        for tok in NUMBER_RE.findall(it["why_it_matters"]):
            digits = re.sub(r"[^0-9]", "", tok)
            if digits and digits not in digits_full:
                bad = True
                break
        if bad:
            continue
        out.append(it)
        if len(out) >= MAX_ITEMS:
            break
    return out


def _settle_fineprint(text: str, full_text: str) -> tuple[bool, list[dict] | None]:
    """Settled when the reply parses to valid items, or parses
    cleanly to nothing (nothing worth surfacing — stop the
    chain). Unsettled when garbled or everything fails
    validation (try the next model)."""
    items, ok = parse_fineprint_json(text)
    if not ok:
        return False, None
    valid = validate_fineprint(items, full_text)
    if valid:
        return True, valid
    if items == []:
        return True, []
    return False, None


async def extract_fineprint_async(passages, release_head, quarter_label, full_text,
                                  llm_call=None, ai=None, api_key: str = "") -> list[dict]:
    """One extraction call down the story chain (Workers AI, then
    gateway models, then direct OpenRouter). No deterministic
    fallback: no items is a valid, hiding result."""
    if not passages and not release_head:
        return []
    system, user = fineprint_prompt(passages, release_head, quarter_label)
    if ai is not None:
        try:
            result = await asyncio.wait_for(call_workers_ai(ai, WORKERS_AI_MODEL, system, user),
                                            timeout=WORKERS_AI_TIMEOUT_S)
            settled, out = _settle_fineprint((result or {}).get("text", ""), full_text)
            if settled:
                return out
        except Exception:
            pass
        for model in MODELS:
            try:
                result = await asyncio.wait_for(call_gateway_binding(ai, model, system, user),
                                                timeout=GATEWAY_TIMEOUT_S)
                settled, out = _settle_fineprint((result or {}).get("text", ""), full_text)
                if settled:
                    return out
            except Exception:
                continue
    if llm_call is None and not api_key:
        return []
    caller = llm_call or (lambda model, s, u: _call_openrouter_async(model, s, u, api_key))
    for model in MODELS:
        try:
            result = await asyncio.wait_for(caller(model, system, user), timeout=60)
            settled, out = _settle_fineprint((result or {}).get("text", ""), full_text)
            if settled:
                return out
        except Exception:
            continue
    return []


def extract_fineprint_sync(passages, release_head, quarter_label, full_text,
                           llm_call=None, api_key: str = "") -> list[dict]:
    """Sync twin (Docker path): direct OpenRouter chain only."""
    if not passages and not release_head:
        return []
    if llm_call is None and not api_key:
        return []
    system, user = fineprint_prompt(passages, release_head, quarter_label)
    caller = llm_call or (lambda model, s, u: _call_openrouter(model, s, u, api_key))
    for model in MODELS:
        try:
            result = caller(model, system, user)
            settled, out = _settle_fineprint((result or {}).get("text", ""), full_text)
            if settled:
                return out
        except Exception:
            continue
    return []


async def fetch_quarterly_10q_texts_async(ticker: str, quarter_end_iso: str,
                                          fetch_json=_afetch_json, fetch_text=_afetch_text):
    """(this_quarter_text, last_quarter_text, this_url, last_url)
    for the two most recent 10-Qs with reportDate <= quarter_end,
    or (\"\", \"\", \"\", \"\") when anything is missing. fetch_* are
    injectable for tests."""
    t = ticker.strip().upper()
    tickers = await fetch_json("https://www.sec.gov/files/company_tickers.json",
                               headers=EDGAR_HEADERS)
    cik = None
    for v in (tickers or {}).values():
        if isinstance(v, dict) and v.get("ticker") == t:
            cik = int(v["cik_str"])
            break
    if not cik:
        return "", "", "", ""
    subs = await fetch_json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json",
                            headers=EDGAR_HEADERS)
    recent = (subs.get("filings", {}) or {}).get("recent", {}) or {}
    forms = recent.get("form", []) or []
    dates = recent.get("reportDate", []) or []
    accs = recent.get("accessionNumber", []) or []
    docs = recent.get("primaryDocument", []) or []
    picked = []
    for form, rdate, acc, doc in zip(forms, dates, accs, docs):
        if form == "10-Q" and rdate and rdate <= quarter_end_iso:
            picked.append((rdate, acc, doc))
        if len(picked) == 2:
            break
    texts, urls = [], []
    for rdate, acc, doc in picked:
        base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/"
        try:
            raw = await fetch_text(base + doc, headers=EDGAR_HEADERS)
            stripped = strip_html(raw)
        except Exception:
            stripped = ""
        texts.append(stripped)
        urls.append(base + doc)
    while len(texts) < 2:
        texts.append("")
        urls.append("")
    return texts[0], texts[1], urls[0], urls[1]


def _sync_get(url: str, want_json: bool):
    import gzip
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, headers=EDGAR_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            return json.loads(raw) if want_json else raw.decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"EDGAR HTTP {e.code} for {url}") from None


def fetch_quarterly_10q_texts_sync(ticker: str, quarter_end_iso: str):
    """Sync twin of fetch_quarterly_10q_texts_async."""
    t = ticker.strip().upper()
    tickers = _sync_get("https://www.sec.gov/files/company_tickers.json", True)
    cik = None
    for v in (tickers or {}).values():
        if isinstance(v, dict) and v.get("ticker") == t:
            cik = int(v["cik_str"])
            break
    if not cik:
        return "", "", "", ""
    subs = _sync_get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", True)
    recent = (subs.get("filings", {}) or {}).get("recent", {}) or {}
    picked = []
    for form, rdate, acc, doc in zip(recent.get("form", []) or [],
                                     recent.get("reportDate", []) or [],
                                     recent.get("accessionNumber", []) or [],
                                     recent.get("primaryDocument", []) or []):
        if form == "10-Q" and rdate and rdate <= quarter_end_iso:
            picked.append((rdate, acc, doc))
        if len(picked) == 2:
            break
    texts, urls = [], []
    for rdate, acc, doc in picked:
        base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/"
        try:
            stripped = strip_html(_sync_get(base + doc, False))
        except Exception:
            stripped = ""
        texts.append(stripped)
        urls.append(base + doc)
    while len(texts) < 2:
        texts.append("")
        urls.append("")
    return texts[0], texts[1], urls[0], urls[1]


def _source_for(section: str, this_url: str, release_url: str) -> str:
    """Per-item source link: the model names sections "MD&A",
    "Notes" or "Release"; only Release items point at the
    exhibit, everything else at this quarter's 10-Q."""
    if "release" in (section or "").lower():
        return release_url or this_url
    return this_url


def build_fineprint_inputs(this_text: str, last_text: str, release_text: str):
    """Pure diff+rank step (shared by both paths, unit-tested):
    returns (passages, release_head, full_text) where full_text
    is what validation checks quotes/numbers against."""
    this_sections = extract_sections(this_text)
    last_sections = extract_sections(last_text)
    passages = []
    for key in ("mda", "notes"):
        new, changed = diff_paragraphs(
            split_paragraphs(this_sections[key]),
            split_paragraphs(last_sections[key]))
        for p in rank_passages(new, changed):
            passages.append({**p, "section": key})
    # Rank across both sections together (keyword + newness),
    # keeping the section tag on each passage.
    passages = sorted(passages, key=lambda d: (d["kind"] != "new", not d["keyword"]))[:MAX_PASSAGES]
    full_text = "\n\n".join(x for x in (this_text, last_text, release_text or "") if x)
    return passages, (release_text[:4000] if release_text else ""), full_text


async def fineprint_for_pack_async(ticker: str, quarter_end_iso: str, quarter_label: str = "",
                                   llm_call=None, ai=None, api_key: str = ""):
    """Best-effort end-to-end async fine-print step: (items,
    source_urls). Any failure yields ([], []), never an
    exception, so the briefing stands."""
    try:
        this_text, last_text, this_url, last_url = await fetch_quarterly_10q_texts_async(
            ticker, quarter_end_iso)
        if not this_text:
            return [], []
        release_text, release_url = await fetch_release_text_async(ticker, quarter_end_iso)
        passages, release_head, full_text = build_fineprint_inputs(
            this_text, last_text, release_text or "")
        items = await extract_fineprint_async(passages, release_head, quarter_label, full_text,
                                              llm_call=llm_call, ai=ai, api_key=api_key)
        if not items:
            return [], []
        urls = [u for u in (this_url, release_url) if u]
        for it in items:
            it["source_url"] = _source_for(it.get("section", ""), this_url, release_url)
        return items, urls
    except Exception:
        return [], []


def fineprint_for_pack_sync(ticker: str, quarter_end_iso: str, quarter_label: str = "",
                            llm_call=None, api_key: str = ""):
    """Sync twin (Docker path): same diff, direct OpenRouter chain."""
    try:
        this_text, last_text, this_url, last_url = fetch_quarterly_10q_texts_sync(
            ticker, quarter_end_iso)
        if not this_text:
            return [], []
        release_text, release_url = fetch_release_text_sync(ticker, quarter_end_iso)
        passages, release_head, full_text = build_fineprint_inputs(
            this_text, last_text, release_text or "")
        items = extract_fineprint_sync(passages, release_head, quarter_label, full_text,
                                       llm_call=llm_call, api_key=api_key)
        if not items:
            return [], []
        urls = [u for u in (this_url, release_url) if u]
        for it in items:
            it["source_url"] = _source_for(it.get("section", ""), this_url, release_url)
        return items, urls
    except Exception:
        return [], []
