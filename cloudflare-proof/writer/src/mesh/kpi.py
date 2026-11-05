"""Company KPIs from the earnings release (exhibit 99.1) — Batch 22.

Why a release, not XBRL: the metrics Tej asked for (Dutch Bros
same-shop sales, system sales, shop counts, outlook) are not
standard XBRL tags — they live in the earnings release attached
to the quarter's 8-K as exhibit 99.1. So this module fetches
that exhibit, asks one LLM call (the same free chain the story
uses) to extract {name, value, unit, period} items plus outlook
items, and validates every value verbatim against the release
text before anything reaches the user. An item whose value is
not in the release is dropped, never patched.

Placement rules (ADR 043, binding):
- The KPI step runs AFTER the Critic gate, so a KPI failure can
  never block a verified briefing. Any exception anywhere here
  yields ([], "") — the section hides, the briefing stands.
- KPIs are NOT part of the Critic-verified claims and are NOT
  fed to the Writer's story prompt in v1 (the story validator
  only allows numbers from claims + transcript; a KPI number in
  the story would drop the whole story).
- The frontend labels the section release-extracted, never
  Critic-verified, and links the exhibit.

8-K selection: the quarter's earnings 8-K is picked from the
submissions feed as the earliest 8-K filed after the pack's
quarter_end and within 75 days (the Batch 7 window). It is
deliberately independent of the Scout's filing pick, so it
works for older-quarter views too. V1 limit: only the
submissions "recent" window is searched — a very old quarter
whose 8-K has rolled into the older-filings shards yields no
KPIs, gracefully.
"""
import asyncio
import gzip
import html as _html
import json
import re
import urllib.error
import urllib.request

from .edgar import UA as EDGAR_UA
from .gateway_binding import GATEWAY_TIMEOUT_S, call_gateway_binding
from .llm import MODELS, _call_openrouter
from .worker_ai import WORKERS_AI_MODEL, WORKERS_AI_TIMEOUT_S, call_workers_ai
from .worker_http import fetch_json as _afetch_json
from .worker_http import fetch_text as _afetch_text

EXHIBIT_991_RE = re.compile(r"ex(?:hibit)?[-_]?99[-_.]?1", re.I)
RELEASE_TEXT_CAP = 20000
MAX_KPIS = 12
EDGAR_HEADERS = {"User-Agent": EDGAR_UA}


def exhibit_991_candidates(items) -> list:
    """Exhibit 99.1 filenames from an EDGAR index.json directory
    listing. Filers name it unpredictably (a2026-q3_ex991.htm,
    ex99-1.htm, exhibit991.htm), so match the ex99.1 shape, not
    one literal name; HTML only, never the .txt bundle."""
    out = []
    for it in items or []:
        name = (it or {}).get("name", "") if isinstance(it, dict) else ""
        if name and EXHIBIT_991_RE.search(name) and name.lower().endswith((".htm", ".html")):
            out.append(name)
    return out


def strip_html(raw: str) -> str:
    """Release HTML -> plain text: drop scripts/styles, strip
    tags, unescape entities, collapse whitespace. A typical
    500KB exhibit becomes ~30KB of text."""
    text = re.sub(r"<script.*?</script>", " ", raw, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = _html.unescape(text)
    text = re.sub(r"[ \t\r\u00a0]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def _norm(s: str) -> str:
    """Normalization for the verbatim check: case, currency
    symbols, thousands separators and whitespace are formatting,
    not content — "5.4%", "$5.4 %" and "5.4" all normalize alike
    only when the digits match."""
    return re.sub(r"[\s$,]", "", str(s).lower())


def value_in_text(value: str, text: str) -> bool:
    """True when the value's digits appear in the release text
    under normalization. A trailing % is optional on either side
    ("5.4" in the text satisfies a "5.4%" value and vice versa).
    Small integers match weakly by construction — the same
    standard the story validator applies to numbers — so the
    section label, not this check, carries the honesty."""
    n_text = _norm(text)
    v = _norm(value)
    if not v:
        return False
    if v in n_text:
        return True
    if v.endswith("%") and v[:-1] in n_text:
        return True
    if v + "%" in n_text:
        return True
    return False


def validate_kpis(items, release_text: str) -> list:
    """Drop every item whose value is not verbatim in the release
    (never patched), normalize kinds, cap the list."""
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        name = str(it.get("name", "")).strip()
        value = str(it.get("value", "")).strip()
        if not name or not value:
            continue
        if not value_in_text(value, release_text):
            continue
        out.append({"name": name, "value": value,
                    "unit": str(it.get("unit", "")).strip(),
                    "period": str(it.get("period", "")).strip(),
                    "kind": "outlook" if str(it.get("kind", "")).strip().lower() == "outlook" else "metric"})
    return out[:MAX_KPIS]


def kpi_prompt(release_text: str) -> tuple:
    """KPIs only (Batch 40 split). Standard financials are excluded
    on purpose: revenue, net income, EPS and EBITDA already live
    in the Critic-verified claims, so repeating them here would
    add noise, not signal. The diagram is a separate, smaller
    call (diagram_prompt) — the combined prompt's long JSON
    output timed out on Workers AI (60s) while the story prompt
    completes, so the two halves run apart."""
    system = ("You extract company-specific operating KPIs from an earnings release. "
              "Return JSON only, no prose, no markdown outside the JSON object.")
    user = ("Extract the company's operating KPIs from this earnings release. "
            "Include same-store / same-shop sales, shop or store counts and openings, "
            "sales volumes, users, subscribers, transactions, backlog, and any outlook "
            "or guidance figures. Mark outlook/guidance items \"kind\": \"outlook\", "
            "everything else \"kind\": \"metric\". Copy each value EXACTLY as written "
            "in the text (including % and $ signs). Only include numbers that appear "
            "in the text. Do NOT include revenue, net income, EPS, EBITDA or margins — "
            "those are covered elsewhere. If nothing qualifies, return {\"kpis\": []}. "
            "Period is the quarter or year the value refers to (e.g. \"Q3 2026\").\n\n"
            f"Release text:\n\n{release_text[:RELEASE_TEXT_CAP]}\n\n"
            "Return {\"kpis\": [{\"name\": ..., \"value\": ..., \"unit\": ..., "
            "\"period\": ..., \"kind\": \"metric\"|\"outlook\"}]}.")
    return system, user


DIAGRAM_TEXT_CAP = 6000


def diagram_prompt(kpis: list, release_text: str) -> tuple:
    """Diagram only (Batch 40 split): the business-model flow,
    grounded only in this release text — its company description
    and highlights, which sit early in a typical release (BROS's
    About paragraph is 14% through its text, inside the 6,000-char
    window). The extracted KPIs ride along so the model knows the
    business. Small input, small output: it finishes well inside
    the 60s Workers AI timeout that killed the combined call."""
    names = ", ".join(str(k.get("name", "")) for k in kpis if isinstance(k, dict))
    system = ("You describe how a company makes money as a flow diagram. "
              "Return JSON only, no prose, no markdown outside the JSON object.")
    user = (f"The company's operating KPIs are: {names}. "
            "Describe how the company makes money as a \"diagram\" object, "
            "grounded ONLY in this release text (its company description and "
            "highlights): {\"nodes\": [{\"id\": ..., \"label\": ..., \"role\": ...}], "
            "\"edges\": [{\"from\": ..., \"to\": ..., \"kind\": ..., \"label\": ...}]}. "
            "Roles are exactly: company (the company itself, exactly one node), "
            "payer (who pays), user (who uses the product), partner (channels, "
            "creators or suppliers who help deliver it). Node labels are 1-3 words, "
            "edge labels at most 4 words, at most 8 nodes and 10 edges. NO numbers "
            "anywhere in any label. Edge kind is \"money\" for cash flowing or "
            "\"value\" for product, service or attention flowing. If the release "
            "does not describe a clear model, return {\"diagram\": null}.\n\n"
            f"Release text:\n\n{release_text[:DIAGRAM_TEXT_CAP]}\n\n"
            "Return {\"diagram\": {\"nodes\": [...], \"edges\": [...]}}.")
    return system, user


def _extract_json_obj(text: str):
    """The JSON object in one model reply, or (None, False).
    Shared by the KPI and diagram parsers: fence-stripped, first
    { to last }, one retry with trailing commas stripped (Batch
    36 — the one unambiguous repair). Anything else garbled
    (unclosed strings, truncated output) fails cleanly."""
    if not text:
        return None, False
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        return None, False
    try:
        obj = json.loads(cleaned[start:end + 1])
    except (ValueError, TypeError):
        repaired = re.sub(r",\s*([}\]])", r"\1", cleaned[start:end + 1])
        if repaired != cleaned[start:end + 1]:
            try:
                obj = json.loads(repaired)
            except (ValueError, TypeError):
                return None, False
        else:
            return None, False
    if not isinstance(obj, dict):
        return None, False
    return obj, True


def parse_kpi_response(text: str) -> tuple:
    """Parse one extraction reply: (kpi items, diagram dict-or-None,
    parsed-ok). A reply that parses to no KPIs and no diagram is a
    real answer (the release has nothing), distinct from a garbled
    reply (parsed-ok False) — the chain treats them differently."""
    obj, ok = _extract_json_obj(text)
    if not ok:
        return [], None, False
    items = obj.get("kpis", obj.get("metrics", []))
    if not isinstance(items, list):
        items = []
    diagram = obj.get("diagram")
    if not isinstance(diagram, dict):
        diagram = None
    return items, diagram, True


def parse_diagram_response(text: str) -> tuple:
    """Parse one diagram reply (Batch 40 split): (diagram
    dict-or-None, parsed-ok)."""
    obj, ok = _extract_json_obj(text)
    if not ok:
        return None, False
    diagram = obj.get("diagram")
    if not isinstance(diagram, dict):
        return None, True
    return diagram, True


def parse_kpi_json(text: str) -> list:
    """Items only (parse_kpi_response's first element)."""
    return parse_kpi_response(text)[0]


DIAGRAM_ROLES = {"payer", "user", "company", "partner"}


def _clean_label(value, max_words: int, allow_empty: bool):
    """A diagram label: word-capped, digit-free (the no-numbers
    rule — a label like "250 shops" would smuggle a figure into
    an unverified visual). None when invalid."""
    t = str(value or "").strip()
    if not t and not allow_empty:
        return None
    if re.search(r"\d", t):
        return None
    words = t.split()
    if len(words) > max_words:
        return None
    if not words and not allow_empty:
        return None
    return t


def validate_diagram(spec) -> dict | None:
    """Validate + salvage a diagram spec. Invalid nodes/edges are
    dropped (edges referencing dropped nodes go with them); the
    result must still have at least 2 nodes, at least 1 edge, and
    exactly one company node, or there is no diagram at all.
    The spec's icon field, if any, is dropped: the role fixes the
    icon at render time, so the model cannot invent icon names."""
    if not isinstance(spec, dict):
        return None
    nodes_in = spec.get("nodes", [])
    edges_in = spec.get("edges", [])
    if not isinstance(nodes_in, list) or not isinstance(edges_in, list):
        return None
    nodes, seen = [], set()
    for n in nodes_in[:8]:
        if not isinstance(n, dict):
            continue
        nid = str(n.get("id", "")).strip()
        role = str(n.get("role", "")).strip().lower().replace("_", "-")
        role = {"partner-channel": "partner"}.get(role, role)
        label = _clean_label(n.get("label", ""), 3, allow_empty=False)
        if not nid or nid in seen or role not in DIAGRAM_ROLES or label is None:
            continue
        seen.add(nid)
        nodes.append({"id": nid, "label": label, "role": role})
    if sum(1 for n in nodes if n["role"] == "company") != 1:
        return None
    edges = []
    for e in edges_in[:10]:
        if not isinstance(e, dict):
            continue
        f = str(e.get("from", "")).strip()
        t = str(e.get("to", "")).strip()
        kind = str(e.get("kind", "")).strip().lower()
        label = _clean_label(e.get("label", ""), 4, allow_empty=True)
        if f not in seen or t not in seen or kind not in ("money", "value") or label is None:
            continue
        edges.append({"from": f, "to": t, "kind": kind, "label": label or ""})
    if len(nodes) < 2 or not edges:
        return None
    return {"nodes": nodes, "edges": edges}


def pick_earnings_8k(recent: dict, quarter_end_iso: str):
    """Earliest 8-K filed after quarter_end and within 75 days,
    from a submissions 'recent' block ({form, filingDate,
    accessionNumber} parallel lists). None when nothing fits."""
    try:
        from datetime import date, timedelta
        qe = date.fromisoformat(quarter_end_iso)
    except (ValueError, TypeError):
        return None
    best = None
    forms = recent.get("form", []) or []
    dates = recent.get("filingDate", []) or []
    accs = recent.get("accessionNumber", []) or []
    for f, d, a in zip(forms, dates, accs):
        if f != "8-K":
            continue
        try:
            fd = date.fromisoformat(d)
        except (ValueError, TypeError):
            continue
        if qe < fd <= qe + timedelta(days=75):
            if best is None or fd < best[0]:
                best = (fd, a)
    return best[1] if best else None


async def fetch_release_text_async(ticker: str, quarter_end_iso: str,
                                   fetch_json=_afetch_json, fetch_text=_afetch_text):
    """(stripped release text, exhibit URL) for the quarter's
    earnings 8-K exhibit 99.1, or (None, "") when anything is
    missing. fetch_* are injectable for tests."""
    t = ticker.strip().upper()
    tickers = await fetch_json("https://www.sec.gov/files/company_tickers.json",
                               headers=EDGAR_HEADERS)
    cik = None
    for v in (tickers or {}).values():
        if isinstance(v, dict) and v.get("ticker") == t:
            cik = int(v["cik_str"])
            break
    if not cik:
        return None, ""
    subs = await fetch_json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json",
                            headers=EDGAR_HEADERS)
    accession = pick_earnings_8k((subs.get("filings", {}) or {}).get("recent", {}), quarter_end_iso)
    if not accession:
        return None, ""
    base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/"
    index = await fetch_json(base + "index.json", headers=EDGAR_HEADERS)
    for name in exhibit_991_candidates((index.get("directory", {}) or {}).get("item", [])):
        raw = await fetch_text(base + name, headers=EDGAR_HEADERS)
        stripped = strip_html(raw)
        if len(stripped) > 2000:
            return stripped, base + name
    return None, ""


def _sync_get_json(url: str):
    req = urllib.request.Request(url, headers=EDGAR_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"EDGAR HTTP {e.code} for {url}") from None


def _sync_get_text(url: str) -> str:
    req = urllib.request.Request(url, headers=EDGAR_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            return raw.decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"EDGAR HTTP {e.code} for {url}") from None


def fetch_release_text_sync(ticker: str, quarter_end_iso: str):
    """Sync twin of fetch_release_text_async (Docker path)."""
    t = ticker.strip().upper()
    tickers = _sync_get_json("https://www.sec.gov/files/company_tickers.json")
    cik = None
    for v in (tickers or {}).values():
        if isinstance(v, dict) and v.get("ticker") == t:
            cik = int(v["cik_str"])
            break
    if not cik:
        return None, ""
    subs = _sync_get_json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
    accession = pick_earnings_8k((subs.get("filings", {}) or {}).get("recent", {}), quarter_end_iso)
    if not accession:
        return None, ""
    base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/"
    index = _sync_get_json(base + "index.json")
    for name in exhibit_991_candidates((index.get("directory", {}) or {}).get("item", [])):
        stripped = strip_html(_sync_get_text(base + name))
        if len(stripped) > 2000:
            return stripped, base + name
    return None, ""


def _settle_kpis_reply(text: str, release_text: str, allow_empty: bool = True):
    """Phase-1 settle (Batch 40 split): (settled?, valid_items).
    Settled when the reply yields valid KPIs. A clean-empty parse
    settles only when allow_empty: the first model that returns
    successfully must never settle on empty — a small model often
    misses KPIs the next model finds (Batch 36: BROS's release has
    KPIs, but the chain stopped after one empty reply). Unsettled
    when the reply is garbled or everything in it fails validation
    (try the next model). The diagram is a separate phase now, so
    this function never looks at it."""
    items, _draw_raw, ok = parse_kpi_response(text)
    if not ok:
        return False, None
    valid = validate_kpis(items, release_text)
    if valid:
        return True, valid
    if items == []:
        return (True, []) if allow_empty else (False, None)
    return False, None


async def extract_kpis_async(release_text: str, llm_call=None, ai=None, api_key: str = "",
                             debug: dict | None = None):
    """Two-phase extraction down the story chain (Workers AI, then
    gateway models, then direct OpenRouter), returning
    (kpi items, diagram-or-None). Phase 1 extracts KPIs alone;
    phase 2 draws the diagram from the extracted KPIs, best-effort,
    on the legs from the KPI winner onward. Batch 40 split: the
    combined prompt's long JSON output timed out on Workers AI
    (60s) while the story prompt completes, so each half runs
    apart and finishes inside the timeout. No deterministic
    fallback: no KPIs and no diagram is a valid, hiding result.
    debug (optional dict, filled in place, Batches 38-39):
    {replies, settled_on, last_parse_ok, last_reply_head, errors,
    diagram} — replies counts phase-1 returns only."""
    system, user = kpi_prompt(release_text)
    # Batch 36: allow_empty turns on only from the SECOND model
    # that returns successfully — a single empty verdict never
    # ends the chain. `replies` counts successful returns only:
    # a timeout or provider error does not count as an opinion.
    replies = 0
    last_text = ""
    last_ok = False

    def _note(text):
        nonlocal last_text, last_ok
        last_text = text or ""
        last_ok = parse_kpi_response(last_text)[2]
        if debug is not None:
            debug["replies"] = replies
            debug["last_parse_ok"] = last_ok
            debug["last_reply_head"] = last_text[:200]

    def _fail(leg, exc):
        # Batch 39: record HOW each leg failed (timeout vs instant
        # error vs auth) — error strings name the failure, never
        # a secret.
        if debug is not None:
            debug.setdefault("errors", []).append(
                {"leg": leg, "error": f"{type(exc).__name__}: {exc}"[:160]})

    # Ordered legs: (name, async call, timeout). Phase 2 resumes
    # from the phase-1 winner, so the legs list is built once.
    legs = []
    if ai is not None:
        legs.append(("workers_ai", lambda s, u: call_workers_ai(ai, WORKERS_AI_MODEL, s, u),
                     WORKERS_AI_TIMEOUT_S))
        for m in MODELS:
            legs.append((f"gateway:{m}", lambda s, u, m=m: call_gateway_binding(ai, m, s, u),
                         GATEWAY_TIMEOUT_S))
    openrouter_caller = None
    if llm_call is not None or api_key:
        openrouter_caller = llm_call or (lambda model, s, u: _call_openrouter_async(model, s, u, api_key))
        for m in MODELS:
            legs.append((f"openrouter:{m}", lambda s, u, m=m: openrouter_caller(m, s, u), 60))

    # Phase 1: KPIs alone.
    items = None
    winner = None
    for idx, (leg, fn, timeout) in enumerate(legs):
        try:
            result = await asyncio.wait_for(fn(system, user), timeout=timeout)
            replies += 1
            _note((result or {}).get("text", ""))
            settled, valid = _settle_kpis_reply(last_text, release_text, allow_empty=replies > 1)
            if settled:
                items = valid
                winner = idx
                break
        except Exception as exc:
            _fail(leg, exc)
            continue
    if items is None:
        if debug is not None:
            # No OpenRouter leg to try at all (and the AI legs, if
            # any, all failed) — the old "no_key" outcome.
            debug["settled_on"] = "no_key" if openrouter_caller is None else "exhausted"
            debug["replies"] = replies
        return [], None
    if debug is not None:
        debug["settled_on"] = "items" if items else "empty"

    # Phase 2: diagram from the extracted KPIs, best-effort. A
    # failed diagram never loses the KPIs; it runs even on an
    # empty KPI settle (a release can have a clear business model
    # and no operating KPIs).
    dsystem, duser = diagram_prompt(items, release_text)
    diagram = None
    for leg, fn, timeout in legs[winner:]:
        try:
            result = await asyncio.wait_for(fn(dsystem, duser), timeout=timeout)
            draw_raw, ok = parse_diagram_response((result or {}).get("text", ""))
            if ok:
                diagram = validate_diagram(draw_raw)
                if diagram is not None:
                    break
        except Exception as exc:
            _fail(f"diagram:{leg}", exc)
            continue
    if debug is not None:
        debug["diagram"] = "ok" if diagram is not None else "none"
    return items, diagram


async def _call_openrouter_async(model: str, system: str, user: str, api_key: str) -> dict:
    """Async twin of llm._call_openrouter (worker_http POST)."""
    from .worker_http import post_json
    payload = {"model": model,
               "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
               "temperature": 0.2, "max_tokens": 1800}
    headers = {"Authorization": f"Bearer {api_key}",
               "HTTP-Referer": "https://example.com/agent-mesh-earnings",
               "X-Title": "Agent Mesh Earnings"}
    body = await post_json("https://openrouter.ai/api/v1/chat/completions", payload, headers=headers)
    if isinstance(body, dict) and body.get("error"):
        err = body["error"]
        raise RuntimeError(f"OpenRouter error {err.get('code', '')}: {err.get('message', '')}")
    text = (body.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
    return {"text": text, "model": model}


def extract_kpis_sync(release_text: str, llm_call=None, api_key: str = "",
                      debug: dict | None = None):
    """Sync twin (Docker path): direct OpenRouter chain only,
    returning (kpi items, diagram-or-None). Same Batch 40
    two-phase split as the async twin. debug: same Batches 38-39
    telemetry dict, filled in place."""
    if llm_call is None and not api_key:
        if debug is not None:
            debug["settled_on"] = "no_key"
            debug["replies"] = 0
        return [], None
    system, user = kpi_prompt(release_text)
    caller = llm_call or (lambda model, s, u: _call_openrouter(model, s, u, api_key))
    # Batch 36: same rule as the async twin — a single empty
    # verdict never ends the chain; only the second successful
    # reply may settle on empty.
    replies = 0
    last_text = ""
    last_ok = False

    def _note(text):
        nonlocal last_text, last_ok
        last_text = text or ""
        last_ok = parse_kpi_response(last_text)[2]
        if debug is not None:
            debug["replies"] = replies
            debug["last_parse_ok"] = last_ok
            debug["last_reply_head"] = last_text[:200]

    def _fail(leg, exc):
        if debug is not None:
            debug.setdefault("errors", []).append(
                {"leg": leg, "error": f"{type(exc).__name__}: {exc}"[:160]})

    # Phase 1: KPIs alone.
    items = None
    winner = None
    for idx, model in enumerate(MODELS):
        try:
            result = caller(model, system, user)
            replies += 1
            _note((result or {}).get("text", ""))
            settled, valid = _settle_kpis_reply(last_text, release_text, allow_empty=replies > 1)
            if settled:
                items = valid
                winner = idx
                break
        except Exception as exc:
            _fail(f"openrouter:{model}", exc)
            continue
    if items is None:
        if debug is not None:
            debug["settled_on"] = "exhausted"
            debug["replies"] = replies
        return [], None
    if debug is not None:
        debug["settled_on"] = "items" if items else "empty"

    # Phase 2: diagram from the extracted KPIs, best-effort.
    dsystem, duser = diagram_prompt(items, release_text)
    diagram = None
    for model in MODELS[winner:]:
        try:
            result = caller(model, dsystem, duser)
            draw_raw, ok = parse_diagram_response((result or {}).get("text", ""))
            if ok:
                diagram = validate_diagram(draw_raw)
                if diagram is not None:
                    break
        except Exception as exc:
            _fail(f"diagram:openrouter:{model}", exc)
            continue
    if debug is not None:
        debug["diagram"] = "ok" if diagram is not None else "none"
    return items, diagram


async def kpis_for_pack_async(ticker: str, quarter_end_iso: str, llm_call=None,
                              ai=None, api_key: str = "", debug: dict | None = None):
    """Best-effort end-to-end async KPI step: (items, diagram,
    source_url). Any failure — no 8-K, no exhibit, no key, every
    model failing — yields ([], None, ""), never an exception, so
    the briefing stands. debug (optional dict, Batch 38) records
    the fetch outcome and the extraction telemetry."""
    try:
        text, url = await fetch_release_text_async(ticker, quarter_end_iso)
        if debug is not None:
            debug["fetched_chars"] = len(text or "")
            debug["fetched_url"] = url or ""
        if not text:
            if debug is not None:
                debug["settled_on"] = "no_text"
            return [], None, ""
        items, diagram = await extract_kpis_async(text, llm_call=llm_call, ai=ai, api_key=api_key, debug=debug)
        return items, diagram, url if (items or diagram is not None) else ""
    except Exception:
        if debug is not None:
            debug["settled_on"] = "error"
        return [], None, ""


def kpis_for_pack_sync(ticker: str, quarter_end_iso: str, llm_call=None, api_key: str = "",
                       debug: dict | None = None):
    """Best-effort sync twin."""
    try:
        text, url = fetch_release_text_sync(ticker, quarter_end_iso)
        if debug is not None:
            debug["fetched_chars"] = len(text or "")
            debug["fetched_url"] = url or ""
        if not text:
            if debug is not None:
                debug["settled_on"] = "no_text"
            return [], None, ""
        items, diagram = extract_kpis_sync(text, llm_call=llm_call, api_key=api_key, debug=debug)
        return items, diagram, url if (items or diagram is not None) else ""
    except Exception:
        if debug is not None:
            debug["settled_on"] = "error"
        return [], None, ""
