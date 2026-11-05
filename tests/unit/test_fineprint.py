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
