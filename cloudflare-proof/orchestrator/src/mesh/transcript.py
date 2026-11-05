"""Earnings-call transcript fetcher — Motley Fool public pages.

Why Fool, and why this is deliberately narrow:
- There is no clean free transcript API. API Ninjas' transcript
  endpoint is premium-only, EarningsCalls.dev and EarningsAPI
  charge for programmatic access. Fool publishes transcripts as
  free articles, so a single, rate-limited fetch of a public page
  is the v1 route — no paywall bypass, no Seeking Alpha scraping.
- Coverage is best for US large caps, and Fool's slug includes
  the company name (e.g. alphabet-googl-q3-2026), so discovery
  tries a bounded set of candidate URLs built from the ticker,
  the EDGAR company name, the quarter, and the filing date plus
  the next two days (transcripts usually publish the day after
  the call). If none match, the tool returns unavailable — it
  never invents a transcript, a quote, or a URL.
- The transcript is MANAGEMENT COMMENTARY, not a numbers source.
  This module returns takeaways + summary + a capped prepared-
  remarks excerpt, with the source URL, so the LLM story layer
  can quote management and the user can click through. Claims
  in the briefing table still come only from the filing /
  quarterly history / consensus, never from this excerpt.
"""
import html as html_lib
import re
import urllib.error
import urllib.request
from datetime import date, timedelta

UA = "Mozilla/5.0 (compatible; agent-mesh-earnings/0.1; +https://example.com) AppleWebKit/537.36"
BASE = "https://www.fool.com/earnings/call-transcripts"

_Q_RE = re.compile(r"Q([1-4])\s+(\d{4})")


def _slugify(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"\b(inc|corp|corporation|company|ltd|llc)\b\.?", "", text)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text


def _parse_quarter(quarter_label: str, report_date: str = ""):
    """'Q3 2026' -> (3, 2026). Falls back to the report date's quarter."""
    if quarter_label:
        m = _Q_RE.search(quarter_label)
        if m:
            return int(m.group(1)), int(m.group(2))
    if report_date:
        try:
            d = date.fromisoformat(report_date[:10])
            return (d.month - 1) // 3 + 1, d.year
        except ValueError:
            pass
    return None, None


def candidate_urls(ticker: str, company_name: str = "", quarter_label: str = "",
                   report_date: str = "") -> list[str]:
    """Bounded candidate Fool URLs, most likely first."""
    t = ticker.strip().lower()
    q, year = _parse_quarter(quarter_label, report_date)
    if q is None or year is None:
        return []
    slugs: list[str] = []
    company_slug = _slugify(company_name or "")
    first_word = company_slug.split("-")[0] if company_slug else ""
    for slug in (company_slug, first_word, ""):
        stem = f"{slug}-{t}" if slug else t
        if stem not in slugs:
            slugs.append(stem)
    dates: list[str] = []
    try:
        base_d = date.fromisoformat(report_date[:10])
        for delta in (1, 0, 2):
            dates.append((base_d + timedelta(days=delta)).isoformat())
    except Exception:
        pass
    urls = []
    for d in dates:
        y, m, day = d.split("-")
        for stem in slugs:
            urls.append(f"{BASE}/{y}/{m}/{day}/{stem}-q{q}-{year}-earnings-call-transcript/")
    return urls


def _clean_html(html_text: str) -> str:
    html_text = re.sub(r"<script.*?</script>", " ", html_text, flags=re.S | re.I)
    html_text = re.sub(r"<style.*?</style>", " ", html_text, flags=re.S | re.I)
    # Keep list/paragraph boundaries, otherwise bullet takeaways merge
    # into one long line when tags are stripped.
    html_text = re.sub(r"</(li|p|div|h\d|tr)>", "\n", html_text, flags=re.I)
    html_text = re.sub(r"<li[^>]*>", "\n- ", html_text, flags=re.I)
    html_text = re.sub(r"<br[^>]*>", "\n", html_text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", html_text)
    text = html_lib.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def _section(text: str, start: str, end_markers: list[str]) -> str:
    idx = text.find(start)
    if idx < 0:
        return ""
    body = text[idx + len(start):]
    cut = len(body)
    for marker in end_markers:
        j = body.find(marker)
        if 0 <= j < cut:
            cut = j
    return body[:cut].strip()


def parse_transcript_html(html_text: str, url: str) -> dict:
    """Pure parser (unit-testable, no network). Returns the tool dict."""
    text = _clean_html(html_text)
    if "Full Conference Call Transcript" not in text or "TAKEAWAYS" not in text:
        return {"status": "unavailable", "source": "Motley Fool (public transcript page)",
                "url": url, "reason": "Fetched page is not a Motley Fool earnings-call transcript."}
    participants = _section(text, "CALL PARTICIPANTS", ["TAKEAWAYS"])
    takeaways = _section(text, "TAKEAWAYS", ["RISKS", "SUMMARY", "Full Conference Call Transcript"])
    summary = _section(text, "SUMMARY", ["INDUSTRY GLOSSARY", "Full Conference Call Transcript"])
    full = _section(text, "Full Conference Call Transcript", [])
    # Takeaways are bullet lines; keep them as a list, capped.
    takeaway_lines = [ln.strip(" -•\t") for ln in takeaways.splitlines() if ln.strip()]
    takeaway_lines = [ln for ln in takeaway_lines if len(ln) > 10][:20]
    excerpt = re.sub(r"\s+", " ", full)[:6000]
    return {
        "status": "available",
        "source": "Motley Fool (public transcript page)",
        "url": url,
        "participants": re.sub(r"\s+", " ", participants)[:800],
        "takeaways": takeaway_lines,
        "summary": re.sub(r"\s+", " ", summary)[:2500],
        "excerpt": excerpt,
        "char_count": len(text),
    }


def fetch_transcript(ticker: str, company_name: str = "", quarter_label: str = "",
                     report_date: str = "", quarter: str = "") -> dict:
    """Fetch a transcript for ticker's quarter. quarter_label wins;
    `quarter` is the legacy arg name from the v1 stub."""
    label = quarter_label or quarter
    urls = candidate_urls(ticker, company_name, label, report_date)
    if not urls:
        return {"ticker": ticker.upper(), "status": "unavailable",
                "source": "Motley Fool (public transcript page)",
                "reason": "Cannot derive a transcript URL: need a quarter label (e.g. 'Q3 2026') or a report date."}
    last_error = ""
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
            with urllib.request.urlopen(req, timeout=30) as r:
                html_text = r.read().decode("utf-8", errors="ignore")
                final_url = r.geturl()
        except urllib.error.HTTPError as e:
            last_error = f"HTTP {e.code} for {url}"
            continue
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
            continue
        parsed = parse_transcript_html(html_text, final_url)
        if parsed.get("status") == "available":
            parsed["ticker"] = ticker.upper()
            parsed["quarter"] = label
            return parsed
        last_error = parsed.get("reason", "page is not a transcript")
    return {"ticker": ticker.upper(), "quarter": label, "status": "unavailable",
            "source": "Motley Fool (public transcript page)",
            "reason": f"No matching Motley Fool transcript page found among candidate URLs (last: {last_error}). "
                      "Transcript may not be published yet, or Fool may use a different slug for this company. "
                      "Briefing continues without a transcript — no quotes are invented."}
