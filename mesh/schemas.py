"""Pydantic contracts between agents — see ARCHITECTURE.md Section 8.
If validation fails, the A2A task fails. Agents never pass free-form
LLM text as their contract.
"""
from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, Field

class SourceRef(BaseModel):
    url: str
    publisher: str
    retrieved_at: datetime
    excerpt: str | None = None

class Fact(BaseModel):
    id: str
    metric: str
    value: float
    unit: str = "USD_B"
    period: str
    source: SourceRef
    verified: bool = False

class EvidencePack(BaseModel):
    ticker: str
    company_name: str
    quarter_label: str
    quarter_end: date
    report_date: datetime
    status: Literal["REPORTED", "NOT_REPORTED_YET"]
    facts: list[Fact] = []
    guidance_verbatim: list[str] = []
    consensus: dict | None = None
    price_reaction: dict | None = None
    transcript: dict | None = None
    missing: list[str] = []

class Claim(BaseModel):
    text: str
    value: float | None = None
    derivation: str
    evidence_ids: list[str]

class Analysis(BaseModel):
    ticker: str
    quarter_label: str
    verdict_draft: str
    claims: list[Claim] = []
    beat_miss: list[dict] = []
    drivers: list[str] = []
    risks_and_watch: list[str] = []

class Critique(BaseModel):
    verdict: Literal["PASS", "FAIL"]
    issues: list[dict] = []
    rechecked_facts: list[str] = []

class Briefing(BaseModel):
    ticker: str
    quarter_label: str
    verdict: str
    table: list[dict] = []
    drivers: list[str] = []
    market_reaction: str = ""
    guidance_and_watch: list[str] = []
    sources: list[SourceRef] = []
    story: str = ""
    story_model: str = ""
    story_tokens_in: int | None = None
    story_tokens_out: int | None = None
    story_latency_s: float | None = None
    transcript_url: str = ""
    transcript_excerpt: str = ""
    quarter_end: str = ""
    fine_print: list[dict] = []
    kpis: list[dict] = []
    kpi_source_url: str = ""
    diagram: dict | None = None
    disclaimer: str = "Informational only. Not investment advice."
    trace_id: str
