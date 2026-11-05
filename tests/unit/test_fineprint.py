"""Batch 30: fine-print section extraction, diff, ranking,
validation, and the best-effort pack step (faked fetches + LLM)."""
import json

import mesh.fineprint as fp

THIS_Q = """ITEM 1. FINANCIAL STATEMENTS
Revenue grew this quarter across all segments, with cloud leading the way forward.
ITEM 2. MANAGEMENT'S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION AND RESULTS OF OPERATIONS
Revenue grew 20% this quarter, driven by cloud adoption across enterprise customers worldwide.
The company faces a new litigation matter in Delaware alleging patent infringement by a competitor.
Operating costs rose due to higher headcount and infrastructure spend in the quarter.
ITEM 3. QUANTITATIVE AND QUALITATIVE DISCLOSURES
Market risk is unchanged from the prior quarter in all material respects here.
ITEM 4. NOTES TO CONDENSED CONSOLIDATED FINANCIAL STATEMENTS
The company recorded a $500 million impairment charge related to its legacy hardware division.
Cash and equivalents totaled $10 billion at quarter end, up from $9 billion last quarter.
ITEM 5. OTHER INFORMATION
Nothing else to report in this section of the filing at this time.
"""

LAST_Q = """ITEM 1. FINANCIAL STATEMENTS
Revenue grew last quarter across all segments, with cloud leading the way forward.
ITEM 2. MANAGEMENT'S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION AND RESULTS OF OPERATIONS
Revenue grew 15% last quarter, driven by cloud adoption across enterprise customers worldwide.
Operating costs rose due to higher headcount and infrastructure spend in the quarter.
ITEM 3. QUANTITATIVE AND QUALITATIVE DISCLOSURES
Market risk is unchanged from the prior quarter in all material respects here.
ITEM 4. NOTES TO CONDENSED CONSOLIDATED FINANCIAL STATEMENTS
Cash and equivalents totaled $9 billion at quarter end, up from $8 billion last quarter.
ITEM 5. OTHER INFORMATION
Nothing else to report in this section of the filing at this time.
"""


def test_extract_sections_finds_mda_and_notes():
    secs = fp.extract_sections(THIS_Q)
    assert "litigation matter in Delaware" in secs["mda"]
    assert "impairment charge" in secs["notes"]
    assert "Market risk is unchanged" not in secs["mda"]  # ITEM 3 ends MD&A
    assert fp.extract_sections("no headings here") == {"mda": "", "notes": ""}


def test_diff_and_rank_puts_new_litigation_first():
    passages, head, full = fp.build_fineprint_inputs(THIS_Q, LAST_Q, "")
    texts = [p["text"] for p in passages]
    assert any("litigation matter in Delaware" in t for t in texts)
    # The litigation passage is new + keyworded, so it ranks first.
    assert "litigation matter in Delaware" in passages[0]["text"]
    assert passages[0]["kind"] == "new"
    # The revenue paragraph changed (20% vs 15%) — close match, not new.
    assert any(p["kind"] == "changed" and "Revenue grew 20%" in p["text"] for p in passages)
    # Unchanged paragraphs (operating costs, market risk) are absent.
    assert not any("Operating costs rose" in t for t in texts)


def test_parse_and_validate_drop_bad_items():
    items, ok = fp.parse_fineprint_json(
        '```json\n{"items": [{"section": "Notes", "quote": "q1", "why_it_matters": "w1"}]}\n```')
    assert ok and len(items) == 1
    assert fp.parse_fineprint_json("not json")[1] is False
    assert fp.parse_fineprint_json('{"nope": []}')[1] is False
    full = "The company recorded a $500 million impairment charge. Cash totaled $10 billion."
    good = [{"section": "Notes", "quote": "recorded a $500 million impairment charge",
             "why_it_matters": "A new charge this quarter."}]
    bad_quote = [{"section": "Notes", "quote": "invented quote not in text",
                  "why_it_matters": "Something."}]
    bad_number = [{"section": "Notes", "quote": "recorded a $500 million impairment charge",
                   "why_it_matters": "The charge was $999 million, a record."}]
    valid = fp.validate_fineprint(good + bad_quote + bad_number, full)
    assert valid == good


def test_validate_caps_at_five():
    full = "word " * 200
    items = [{"section": "MD&A", "quote": "word", "why_it_matters": "A point worth noting."} for _ in range(8)]
    assert len(fp.validate_fineprint(items, full)) == 5


def test_fineprint_for_pack_sync_end_to_end(monkeypatch):
    monkeypatch.setattr(fp, "fetch_quarterly_10q_texts_sync",
                        lambda t, q: (THIS_Q, LAST_Q, "https://sec.gov/this-10q", "https://sec.gov/last-10q"))
    monkeypatch.setattr(fp, "fetch_release_text_sync",
                        lambda t, q: ("Release opening: revenue grew.", "https://sec.gov/release"))

    def fake_llm(model, system, user):
        return {"text": json.dumps({"items": [
            {"section": "MD&A",
             "quote": "The company faces a new litigation matter in Delaware alleging patent infringement by a competitor.",
             "why_it_matters": "A new litigation matter disclosed this quarter."},
            {"section": "Notes",
             "quote": "The company recorded a $500 million impairment charge related to its legacy hardware division.",
             "why_it_matters": "A new impairment charge this quarter."},
        ]}), "model": model}

    items, urls = fp.fineprint_for_pack_sync(
        "MSFT", "2026-09-30", "quarter ended 2026-09-30", llm_call=fake_llm)
    assert len(items) == 2
    assert items[0]["source_url"] == "https://sec.gov/this-10q"
    assert "https://sec.gov/this-10q" in urls


def test_fineprint_for_pack_sync_hides_on_llm_failure(monkeypatch):
    monkeypatch.setattr(fp, "fetch_quarterly_10q_texts_sync",
                        lambda t, q: (THIS_Q, LAST_Q, "https://sec.gov/this-10q", "https://sec.gov/last-10q"))
    monkeypatch.setattr(fp, "fetch_release_text_sync", lambda t, q: ("", ""))

    def failing_llm(model, system, user):
        raise RuntimeError("model down")

    items, urls = fp.fineprint_for_pack_sync(
        "MSFT", "2026-09-30", "quarter ended 2026-09-30", llm_call=failing_llm)
    assert items == [] and urls == []


# Newline-free text modelled on a real NVDA 10-Q (Nov 5, 2026):
# strip_html collapses the whole filing to ONE line, so the old
# line-based extract_sections matched both headings on line 0
# and returned the first 60k chars of XBRL header junk for BOTH
# sections. The offset-based version must find the real headings
# past the table of contents and the "See accompanying" footers.
ONE_LINE_Q = (
    "Table of Contents Page Part I Financial Information Item 1. Financial Statements "
    "a) Condensed Consolidated Statements of Income 1 f) Notes to Condensed Consolidated "
    "Financial Statements 8 Item 2. Management's Discussion and Analysis of Financial "
    "Condition and Results of Operations 23 Item 3. Quantitative and Qualitative "
    "Disclosures About Market Risk 30 Item 4. Controls and Procedures 31 "
    "NVIDIA Corporation and Subsidiaries Condensed Consolidated Statements of Income "
    "Revenue 81615 Cost of revenue 12000 See accompanying Notes to Condensed Consolidated "
    "Financial Statements. NVIDIA Corporation and Subsidiaries Notes to Condensed "
    "Consolidated Financial Statements Note 1 describes the basis of presentation and "
    "the significant accounting policies used in these statements. The company recorded "
    "a new warranty accrual of forty million dollars in the current quarter period. "
    "NVIDIA Corporation and Subsidiaries Notes to Condensed Consolidated Financial "
    "Statements (Continued) (Unaudited) Later note text about lease obligations here. "
    "22 Item 2. Management's Discussion and Analysis of Financial Condition and Results "
    "of Operations Forward-Looking Statements This quarterly report contains forward "
    "looking statements about demand for accelerated computing products worldwide. "
    "Revenue grew on strong data center demand across hyperscale customers this quarter. "
    "Item 3. Quantitative and Qualitative Disclosures About Market Risk The company is "
    "exposed to market risk from changes in foreign currency exchange rates worldwide."
)


def test_extract_sections_newline_free_filing():
    secs = fp.extract_sections(ONE_LINE_Q)
    assert secs["mda"] != secs["notes"]
    assert "forward looking statements about demand" in secs["mda"]
    assert "Revenue grew on strong data center demand" in secs["mda"]
    assert "Table of Contents" not in secs["mda"]
    assert "warranty accrual of forty million dollars" not in secs["mda"]
    assert "basis of presentation" in secs["notes"]
    assert "warranty accrual of forty million dollars" in secs["notes"]
    assert "Table of Contents" not in secs["notes"]
    assert "forward looking statements about demand" not in secs["notes"]
    # The notes section ends at Item 2 (MD&A); MD&A ends at Item 3.
    assert "market risk from changes in foreign currency" not in secs["mda"]


def test_diff_paragraphs_fast_and_still_accurate():
    """Regression (Nov 5, 2026): the naive diff ran difflib
    against every previous sentence per current sentence —
    ~1.7s CPU on a real 10-Q pair, killing the Writer at the
    2,000ms CPU budget. The indexed version must stay fast on
    130x130 sentences and keep the changed/new distinction."""
    import time
    base = [f"Operating segment {i} generated revenue of {100 + i} million dollars "
            f"from enterprise customers in the region this quarter." for i in range(130)]
    prev = list(base)
    cur = list(base[:100])
    # 30 changed: one word swapped, still a close match.
    cur += [s.replace("enterprise customers", "hyperscale customers") for s in base[100:130]]
    # 30 genuinely new sentences.
    cur += [f"New disclosure {i}: the company settled a patent dispute involving "
            f"graphics processors and paid an amount in the quarter." for i in range(30)]
    t0 = time.process_time()
    new, changed = fp.diff_paragraphs(cur, prev)
    elapsed = time.process_time() - t0
    assert elapsed < 0.5, f"diff took {elapsed:.2f}s CPU"
    assert len(changed) == 30, f"expected 30 changed, got {len(changed)}"
    assert len(new) == 30, f"expected 30 new, got {len(new)}"
    assert "hyperscale customers" in changed[0]
    assert "patent dispute" in new[0]
