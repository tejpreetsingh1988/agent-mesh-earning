"""Batch 22: KPIs from exhibit 99.1 — pure helpers, validation,
8-K picking, async fetch with fakes, extraction with a fake LLM,
and write_briefing plumbing. Async tests are sync defs wrapping
asyncio.run, per repo convention (no pytest-asyncio)."""
import asyncio

import mesh.kpi as kpi
from mesh.schemas import Analysis, EvidencePack
from mesh.writer import write_briefing


def test_exhibit_991_candidates():
    items = [{"name": "a2026-q3_ex991.htm"}, {"name": "ex99-1.htm"},
             {"name": "exhibit991.htm"}, {"name": "bros-20261104.htm"},
             {"name": "0001866581-26-000178.txt"}, {"name": "R1.htm"},
             {"name": "ex991.pdf"}]
    assert kpi.exhibit_991_candidates(items) == [
        "a2026-q3_ex991.htm", "ex99-1.htm", "exhibit991.htm"]


def test_strip_html():
    raw = ("<html><head><style>.x{color:red}</style><script>var a=1;</script></head>"
           "<body><p>Company-operated same shop sales increased 5.4%.</p>"
           "<p>Opened 48&nbsp;new shops.</p></body></html>")
    text = kpi.strip_html(raw)
    assert "color:red" not in text and "var a=1" not in text
    assert "Company-operated same shop sales increased 5.4%." in text
    assert "Opened 48 new shops." in text


def test_value_in_text():
    text = "Company-operated same shop sales increased 5.4% and revenue grew to $549.8 million."
    assert kpi.value_in_text("5.4%", text)
    assert kpi.value_in_text("5.4", text)
    assert kpi.value_in_text("$549.8 million", text)
    assert not kpi.value_in_text("6.1%", text)
    assert not kpi.value_in_text("", text)


def test_validate_kpis_drops_invented_and_normalizes_kind():
    text = "Same shop sales increased 5.4%. Opened 48 new shops. Goal of 250 shops in 2027."
    items = [{"name": "Company-operated same shop sales", "value": "5.4%", "unit": "%",
              "period": "Q3 2026", "kind": "metric"},
             {"name": "System sales", "value": "$2.0B", "unit": "$B",
              "period": "Q3 2026", "kind": "metric"},
             {"name": "2027 shop opening goal", "value": "250", "unit": "shops",
              "period": "2027", "kind": "Outlook"},
             {"name": "", "value": "5.4%", "unit": "%", "period": "Q3 2026"}]
    out = kpi.validate_kpis(items, text)
    assert [o["name"] for o in out] == [
        "Company-operated same shop sales", "2027 shop opening goal"]
    assert out[1]["kind"] == "outlook"


def test_validate_kpis_caps_at_12():
    text = " ".join(f"metric{i} value {i}" for i in range(20))
    items = [{"name": f"m{i}", "value": str(i), "unit": "", "period": ""} for i in range(20)]
    assert len(kpi.validate_kpis(items, text)) == 12


def test_parse_kpi_json():
    assert kpi.parse_kpi_json('{"kpis": [{"name": "a", "value": "1"}]}') == [{"name": "a", "value": "1"}]
    assert kpi.parse_kpi_json('```json\n{"metrics": [{"name": "b"}]}\n```') == [{"name": "b"}]
    assert kpi.parse_kpi_json("not json at all") == []
    assert kpi.parse_kpi_json("") == []


def test_pick_earnings_8k():
    recent = {"form": ["10-Q", "8-K", "8-K", "8-K"],
              "filingDate": ["2026-10-01", "2026-10-29", "2026-11-04", "2026-12-20"],
              "accessionNumber": ["acc-q", "acc-early", "acc-late", "acc-far"]}
    # Earliest 8-K after 2026-09-30 within 75 days wins.
    assert kpi.pick_earnings_8k(recent, "2026-09-30") == "acc-early"
    assert kpi.pick_earnings_8k(recent, "2026-12-25") is None
    assert kpi.pick_earnings_8k(recent, "not-a-date") is None


def _fake_fetchers():
    async def fetch_json(url, headers=None):
        if "company_tickers" in url:
            return {"0": {"ticker": "BROS", "cik_str": 1866581, "title": "Dutch Bros Inc."}}
        if "submissions" in url:
            return {"filings": {"recent": {
                "form": ["8-K"], "filingDate": ["2026-11-04"],
                "accessionNumber": ["0001866581-26-000178"]}}}
        if "index.json" in url:
            return {"directory": {"item": [{"name": "a2026-q3_ex991.htm"},
                                            {"name": "bros-20261104.htm"}]}}
        raise AssertionError(f"unexpected json url {url}")

    async def fetch_text(url, headers=None):
        assert url.endswith("a2026-q3_ex991.htm")
        return ("<html><body><p>Company-operated same shop sales increased 5.4%.</p>"
                "<p>Opened 48 new shops.</p>" + "<p>filler.</p>" * 500 + "</body></html>")

    return fetch_json, fetch_text


def test_fetch_release_text_async():
    fj, ft = _fake_fetchers()
    text, url = asyncio.run(kpi.fetch_release_text_async("BROS", "2026-09-30",
                                                         fetch_json=fj, fetch_text=ft))
    assert "5.4%" in text and "48 new shops" in text
    assert url.endswith("a2026-q3_ex991.htm")


def test_fetch_release_text_async_no_8k():
    async def fetch_json(url, headers=None):
        if "company_tickers" in url:
            return {"0": {"ticker": "BROS", "cik_str": 1866581, "title": "Dutch Bros Inc."}}
        return {"filings": {"recent": {"form": [], "filingDate": [], "accessionNumber": []}}}

    async def fetch_text(url, headers=None):
        raise AssertionError("should not fetch")

    assert asyncio.run(kpi.fetch_release_text_async("BROS", "2026-09-30",
                                                    fetch_json=fetch_json, fetch_text=fetch_text)) == (None, "")


def test_extract_kpis_async_drops_invented(monkeypatch):
    monkeypatch.setattr(kpi, "MODELS", ["m1", "m2"])
    calls = []

    async def fake_llm(model, system, user):
        calls.append(model)
        return {"text": '{"kpis": ['
                '{"name": "Company-operated same shop sales", "value": "5.4%", "unit": "%", "period": "Q3 2026", "kind": "metric"}, '
                '{"name": "System sales", "value": "$2.0B", "unit": "$B", "period": "Q3 2026", "kind": "metric"}]}'}

    text = "Company-operated same shop sales increased 5.4%."
    items, diagram = asyncio.run(kpi.extract_kpis_async(text, llm_call=fake_llm))
    assert [o["name"] for o in items] == ["Company-operated same shop sales"]
    assert diagram is None
    assert len(calls) == 1


def test_extract_kpis_async_empty_list_stops_chain(monkeypatch):
    monkeypatch.setattr(kpi, "MODELS", ["m1", "m2"])
    calls = []

    async def fake_llm(model, system, user):
        calls.append(model)
        return {"text": '{"kpis": []}'}

    assert asyncio.run(kpi.extract_kpis_async("release text", llm_call=fake_llm)) == ([], None)
    assert calls == ["m1"]


def test_extract_kpis_async_all_models_fail(monkeypatch):
    monkeypatch.setattr(kpi, "MODELS", ["m1", "m2"])

    async def fake_llm(model, system, user):
        raise RuntimeError("provider down")

    assert asyncio.run(kpi.extract_kpis_async("release text", llm_call=fake_llm)) == ([], None)


def test_kpis_for_pack_async_best_effort(monkeypatch):
    # The fetch step fails: the wrapper must yield ([], ""), never raise.
    async def failing_fetch(*args, **kwargs):
        raise RuntimeError("EDGAR down")

    monkeypatch.setattr(kpi, "fetch_release_text_async", failing_fetch)
    assert asyncio.run(kpi.kpis_for_pack_async("BROS", "2026-09-30")) == ([], None, "")


def test_write_briefing_kpi_plumbing():
    from datetime import date, datetime, timezone
    pack = EvidencePack(ticker="BROS", company_name="Dutch Bros Inc.",
                        quarter_label="quarter ended 2026-09-30",
                        quarter_end=date(2026, 9, 30),
                        report_date=datetime(2026, 11, 4, tzinfo=timezone.utc),
                        status="REPORTED")
    analysis = Analysis(ticker="BROS", quarter_label="quarter ended 2026-09-30",
                        verdict_draft="Solid quarter.", claims=[], drivers=[])
    b = write_briefing(pack, analysis, "t1",
                       story_result={"story": "s", "model": "m"},
                       kpi_result={"items": [{"name": "SSS", "value": "5.4%", "unit": "%",
                                              "period": "Q3 2026", "kind": "metric"}],
                                   "source_url": "https://example.com/ex991.htm"})
    assert b.kpis[0]["name"] == "SSS"
    assert b.kpi_source_url == "https://example.com/ex991.htm"
    b2 = write_briefing(pack, analysis, "t2", story_result={"story": "s", "model": "m"})
    assert b2.kpis == [] and b2.kpi_source_url == ""


def test_kpi_prompt_excludes_standard_financials():
    system, user = kpi.kpi_prompt("release")
    assert "Do NOT include revenue" in user
    assert "outlook" in user.lower()
    assert "diagram" in user


def test_extract_kpis_async_returns_valid_diagram():
    async def fake_llm(model, system, user):
        return {"text": '{"kpis": [], "diagram": {"nodes": ['
                '{"id": "p", "label": "Players", "role": "payer"}, '
                '{"id": "c", "label": "Roblox", "role": "company"}, '
                '{"id": "cr", "label": "Creators", "role": "partner"}], '
                '"edges": [{"from": "p", "to": "c", "kind": "money", "label": "buys Robux"}, '
                '{"from": "c", "to": "cr", "kind": "money", "label": "revenue share"}, '
                '{"from": "cr", "to": "p", "kind": "value", "label": "experiences"}]}}'}

    items, diagram = asyncio.run(kpi.extract_kpis_async("release", llm_call=fake_llm))
    assert items == []
    assert diagram is not None and len(diagram["nodes"]) == 3


def test_extract_kpis_async_invalid_diagram_keeps_kpis():
    async def fake_llm(model, system, user):
        return {"text": '{"kpis": [{"name": "SSS", "value": "5.4%", "unit": "%", '
                '"period": "Q3 2026", "kind": "metric"}], "diagram": {"nodes": ['
                '{"id": "c", "label": "Co 250", "role": "company"}], "edges": []}}'}

    items, diagram = asyncio.run(
        kpi.extract_kpis_async("SSS increased 5.4%.", llm_call=fake_llm))
    assert [o["name"] for o in items] == ["SSS"]
    assert diagram is None
