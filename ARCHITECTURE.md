# Agent Mesh Research Lab — Earnings Briefing System
## Architecture Specification v1.0

**Status:** Draft for review before build — 28 Oct 2026
**Scope:** v1 answers one question well: "How was [company]'s recent earnings?"
**Stack (proposed, to lock before Day 1):** Python 3.12, FastMCP for MCP servers, A2A via `a2a-sdk` (Google) with FastAPI services, LangGraph inside each agent for its internal reasoning loop, Pydantic v2 for all schemas, Streamlit for the demo UI, Docker Compose for local run.

---

## 1. Problem and Why This Design

A single LLM answering "How was Google's earnings?" will happily invent numbers, mix GAAP and non-GAAP, and quote last quarter as if it were this quarter. There is no ground truth check.

Earnings are the ideal test for a multi-agent system because the ground truth exists and is checkable:

- A filing exists with exact numbers and a date.
- A consensus estimate exists (with a source that must be named).
- A market reaction exists (price move after the report).
- Interpretation is genuinely debatable (operating strength vs GAAP noise vs cash burn).

So the system is designed around one principle:

> **No number reaches the user unless it came from a tool, and no analysis reaches the user unless the Critic independently re-checked it.**

That is what makes the Scout / Analyst / Critic / Writer split meaningful instead of cosmetic.

## 2. Goals and Non-Goals

### Goals (v1)

1. Answer for any US large-cap ticker: resolve company, find its most recent reported quarter, and produce a verified briefing in under ~90 seconds.
2. Show the mesh working: every A2A task, MCP tool call, and Critic rejection is visible in a trace view.
3. Be reproducible: the same query against the same filing produces the same core numbers. LLM prose may vary; numbers must not.
4. Be publishable: a stranger can clone, set one LLM API key, run `docker compose up`, and ask about GOOGL, NVDA, or AAPL.
5. Teach the real protocols: MCP (tools, resources, prompts) and A2A (Agent Cards, tasks, artifacts) as separate, interoperable layers — not one framework pretending to be both.

### Non-Goals (v1 — explicitly out)

- No buy / sell / hold recommendation, price target, or portfolio advice. Output is informational only, with a disclaimer on every briefing.
- No real-time trading, options, or intraday alerts.
- No non-US tickers, small caps with thin coverage, or multi-quarter forecasting models.
- No user accounts, persistence of personal data, or paid data vendors. All v1 data sources are free / public.
- No charts in v1 (table + text only). Charts are a v1.1 extension.

## 3. User Experience

### Input

Free text, for example:

- "How was Google's recent earnings?"
- "How did NVDA do last quarter?"
- "MSFT earnings?"

### Output: the briefing

A single page with, in order:

1. **Verdict (2 lines max).** Example for GOOGL Q3 2026: "Strong operating quarter, messy GAAP bottom line. Market punished cash burn despite Cloud doubling."
2. **At a glance table:** Revenue, EPS (GAAP), operating income, operating margin, segment revenues, CapEx, free cash flow — each with: this quarter, year-ago, change %, consensus (with source), beat / miss.
3. **What drove it:** 3–5 bullets, each tied to a source.
4. **What the market hated / liked:** after-hours / next-day move, with timestamp and window stated.
5. **Guidance and what to watch next quarter:** only what management actually said; if no guidance was given, say so.
6. **Sources:** every number links to its filing, transcript, or data source. No uncited numbers.
7. **Agent trace (collapsible):** Scout → Analyst → Critic → Writer, with tool calls and any Critic rejections.
8. **Disclaimer:** informational only, not investment advice.

### Worked example — GOOGL Q3 2026 (fixture, not live agent output)

This is the golden test case for v1. Quarter ended 30 Sep 2026, reported after close 28 Oct 2026:

- Total revenue $127.6B, +25% YoY (year-ago $102.3B)
- Operating income $40.6B, +30% YoY, operating margin 31.8%
- Diluted GAAP EPS $2.12, -26% YoY (year-ago $2.87), pressured by an ~$8.7B loss on equity securities (including SpaceX)
- Google Search & other $63.4B, +12% YoY; YouTube ads $11.2B, +9% YoY; Google Services $96.3B, +11% YoY
- Google Cloud $30.7B, +103% YoY; Cloud operating income $11.1B, margin 36.2%
- CapEx $51.4B; free cash flow -$9.1B (second straight negative quarter)
- Consensus (to be labelled by source in the live system): revenue ~$128.2B, EPS ~$2.94–$3.02 depending on vendor — the Critic must flag this range, not pick one silently
- Market reaction: shares fell ~8–9% in after-hours trading after the report

The lesson in this fixture: an Analyst that writes "earnings collapsed" is wrong (operating income rose 30%). An Analyst that writes "great quarter, ignore EPS" is also wrong (cash burn and the miss mattered to the market). The Critic exists to force both truths into the briefing.

## 4. System Architecture

```
User (Streamlit UI / CLI)
        │  HTTP + task_id
        ▼
┌─────────────────────────┐
│ Orchestrator Agent      │  ◄── owns the user task, routes, retries,
│ (FastAPI + A2A client)  │      assembles the final briefing
└──────┬──────────────────┘
       │ A2A (JSON-RPC over HTTP)
       ├──────────┬──────────┬──────────┐
       ▼          ▼          ▼          ▼
   ┌───────┐ ┌────────┐ ┌────────┐ ┌────────┐
   │ Scout │ │Analyst │ │ Critic │ │ Writer │
   │ Agent │ │ Agent  │ │ Agent  │ │ Agent  │
   └───┬───┘ └───┬────┘ └───┬────┘ └────────┘
       │         │          │
       └────┬────┴────┬─────┘
            │ MCP (Streamable HTTP)
       ┌────┴─────────────────────────┐
       │ filings-mcp  │ market-mcp    │
       │ estimates-news-mcp           │
       └──────────────────────────────┘
            │ HTTP (read-only)
       SEC EDGAR │ Company IR │ yfinance / price APIs │ News / transcripts
```

Key separation:

- **A2A is agent-to-agent.** Agents never call each other's LLM directly. They send A2A tasks and receive A2A artifacts.
- **MCP is agent-to-tool.** Agents never scrape a website directly in agent code. All external data comes through an MCP tool, so tool calls are logged, cached, and replaceable.
- **Orchestrator is not a super-agent.** It does no analysis itself. It resolves the ticker, creates the task graph, enforces timeouts and the Critic loop, and returns the briefing or a clean failure.

## 5. The Agents

Each agent is an independent FastAPI service with its own Agent Card, its own LLM loop (LangGraph), and its own MCP client. Each can be run, tested, and replaced alone.

### 5.1 Orchestrator

- Input: raw user text + optional ticker hint.
- Steps:
  1. Resolve ticker: "Google" → GOOGL (Class A, primary listing for the demo; note GOOG exists as Class C and maps to the same Alphabet filing). Ambiguous input → ask a clarifying question, do not guess.
  2. Create `task_id`, start trace.
  3. Scout task → Analyst task → Critic task → (loop back to Analyst up to 2 times if Critic rejects) → Writer task.
  4. Enforce budgets: total wall-clock 90s soft / 150s hard, max 2 Critic rejections, then return best-effort briefing with a "Critic unresolved" flag — never silently drop a rejection.
  5. Return briefing + trace + sources.
- No MCP tools of its own except `resolve_ticker`.

### 5.2 Scout — evidence only, no interpretation

- System instruction: "You collect facts. You do not interpret, summarise beyond extraction, or infer. Every fact carries source_url, retrieved_at, and verbatim excerpt where available."
- MCP tools used: see Section 7.
- Output: `EvidencePack` (Section 8). Must include, or explicitly mark missing:
  - Company name, ticker, exchange, filing type (8-K + press release, 10-Q if available)
  - Quarter end date, report date/time, fiscal quarter label (e.g. Q3 2026)
  - Headline numbers as reported (revenue, EPS, operating income, net income)
  - Segment breakdown as reported
  - CapEx, operating cash flow, free cash flow if disclosed
  - Guidance statements verbatim (or "no guidance given")
  - Consensus estimates with vendor/source label, or "consensus unavailable in free sources"
  - Price: close before report, after-hours move, next-day close if available, with timestamps and windows
  - Transcript / management quotes (short, attributed)
- Failure behaviour: if no filing is found for the "recent" quarter, return `status: NOT_REPORTED_YET` with the next expected earnings date if known. Never fabricate a quarter.

### 5.3 Analyst — compute and interpret, from the EvidencePack only

- System instruction: "Use only numbers in the EvidencePack. Show your arithmetic. Distinguish GAAP vs non-GAAP vs operating performance. State beat/miss only where a consensus source is present."
- Computes:
  - YoY and QoQ change % for every headline and segment line
  - Beat / miss vs consensus, in both $ and %
  - Margin changes (operating margin, segment margin)
  - Drivers: which segments contributed most to growth / drag
  - Cash story: CapEx vs operating cash flow vs FCF, and trend over last 2 quarters if data is present
- Output: `Analysis` (Section 8) with a `claims` list — every claim has `value`, `derivation`, and `evidence_ids` pointing back to Scout facts. No claim without evidence_ids.
- Temperature: low (0.0–0.2). Structured output enforced via Pydantic.

### 5.4 Critic — independent verification, not style review

The Critic does NOT trust the Analyst's evidence_ids. It re-queries MCP tools for a sample (and for all headline numbers) and checks:

1. **Existence:** Does the filing actually contain this number?
2. **Arithmetic:** Is YoY % correct? Is margin = income / revenue?
3. **Label correctness:** GAAP vs adjusted, quarter label, currency, units ($B vs $M).
4. **Beat/miss correctness:** Was consensus actually that number, from that source, at that date?
5. **Omission check:** Is a material fact in the EvidencePack missing from the Analysis? (e.g. FCF negative, one-off loss, guidance cut)
6. **Overclaim check:** Does the Analysis say "beat" when the miss was on the metric that mattered, or vice versa? Does it conflate operating income with net income?
7. **Staleness check:** Is the quarter the most recent reported quarter, not last quarter?
8. **Source check:** Is every claim traceable? Are transcript quotes accurate and attributed?

- Output: `Critique` with `verdict: PASS | FAIL`, `issues[]` (severity: blocker / major / minor), and `required_fixes[]`.
- On FAIL with blockers: Orchestrator returns Analysis + Critique to Analyst for revision. Max 2 loops.
- Critic temperature: 0.0. Critic has its own MCP client — this independence is a core demo point.

### 5.5 Writer — prose only, from approved Analysis

- System instruction: "Write from the approved Analysis only. Do not introduce new numbers, new claims, or new interpretations. If a number is not in the Analysis, do not write it."
- Output: `Briefing` (Section 8) — verdict, table, drivers, market reaction, guidance/watchlist, sources, disclaimer.
- Writer may improve readability, not substance. If Writer needs a missing number, it fails back to Orchestrator rather than inventing it.

## 6. A2A Layer — How Agents Talk

Protocol: A2A JSON-RPC over HTTP, following the public A2A spec pattern. For v1 we implement a pragmatic subset with the `a2a-sdk` Python package; we do not invent a custom protocol and call it A2A.

### 6.1 Agent Card

Every agent serves `GET /.well-known/agent.json`, for example (Scout, abbreviated):

```json
{
  "name": "earnings-scout",
  "description": "Collects earnings evidence from filings, market data, and news via MCP. Returns cited facts only, no interpretation.",
  "url": "http://scout:8001/",
  "version": "1.0.0",
  "capabilities": { "streaming": false },
  "skills": [
    {
      "id": "collect_evidence",
      "name": "Collect earnings evidence",
      "description": "Given a ticker, return an EvidencePack for its most recent reported quarter.",
      "inputModes": ["application/json"],
      "outputModes": ["application/json"]
    }
  ]
}
```

Orchestrator discovers agents by reading these cards at startup (from env-configured URLs in v1, from a registry in v1.1). If a card is missing or a skill is missing, startup fails loudly — no silent fallback to a monolith.

### 6.2 Task Lifecycle

- `tasks/send` → creates a task, returns `task_id`, initial state `submitted`
- States: `submitted → working → input-required | completed | failed | canceled`
- Agent returns `artifacts[]` on completion. Each artifact has `artifactId`, `name` (e.g. `evidence_pack`, `analysis`, `critique`, `briefing`), `parts[]` with `data` (the Pydantic JSON) and, for Writer, `text` (the rendered briefing).
- `input-required` is used only for genuine ambiguity (e.g. ticker clarification), not for normal retries.
- Every A2A message carries `contextId` (the user query session) and `task_id` so the trace view can reconstruct the graph.

### 6.3 Failure Handling in A2A

- Timeout per agent task: Scout 40s, Analyst 30s, Critic 40s, Writer 20s (tunable via env).
- Retry: transient HTTP failure → 1 retry with backoff. LLM failure → fail the task, Orchestrator returns a clean user-facing error, never a partial briefing presented as complete.
- Agent down: Orchestrator marks the run failed and shows which agent failed in the trace. This is a feature for the demo, not a bug to hide.

## 7. MCP Layer — How Agents Get Data

Transport: MCP Streamable HTTP in v1 (so each MCP server is also a service in Docker Compose). Stdio is supported for local Claude Desktop / Inspector testing, but the mesh itself uses HTTP so services can be independent.

All MCP tools are **read-only**. No tool in v1 writes, trades, emails, or posts anything. That is a deliberate safety and demo choice.

### 7.1 filings-mcp

Source of truth for reported numbers. Primary source: SEC EDGAR (free, no key).

| Tool | Inputs | Outputs |
|---|---|---|
| `get_company_facts` | ticker | CIK, name, fiscal year end, recent filings list |
| `get_latest_earnings_filing` | ticker | Filing type, accession, filing date, quarter end, press-release text / URL, 8-K items |
| `get_filing_text` | accession, section | Extracted text for a section (results, segments, guidance) |
| `get_transcript_excerpt` | ticker, quarter | Management quotes, if a transcript source is available; otherwise `unavailable` |
| `list_recent_filings` | ticker, limit | Dated filing list to prove "most recent" |

Caching: filing text cached by accession (immutable). Never cache "latest" resolution for more than 15 minutes.

### 7.2 market-mcp

Price and history. Primary source in v1: yfinance wrapper (free, unofficial — labelled as such in sources).

| Tool | Inputs | Outputs |
|---|---|---|
| `get_price_reaction` | ticker, report_date | Close before report, after-hours move %, next-day close, timestamps, window definition |
| `get_quarterly_history` | ticker, quarters=4 | Revenue, EPS, operating income for prior quarters for YoY/QoQ context |
| `get_company_profile` | ticker | Name, sector, market cap band, share classes (GOOG vs GOOGL note) |

If yfinance is unavailable, market-mcp returns `unavailable` and the briefing states market reaction as unknown — it does not fall back to LLM memory.

### 7.3 estimates-news-mcp

Consensus and context. This is the weakest free-data link — the spec is honest about it.

| Tool | Inputs | Outputs |
|---|---|---|
| `get_consensus_estimates` | ticker, quarter | Revenue/EPS consensus, vendor/source label, as-of date, or `unavailable` with reason |
| `get_earnings_calendar` | ticker | Last report date, next expected date (if published) |
| `get_recent_news` | ticker, days=3 | Headlines, publisher, URL, timestamp — for market-reaction context only, never as a numbers source |

Rule: **News is never a numbers source.** If a number appears only in news and not in a filing, Scout marks it `unverified` and Analyst must not use it as a headline claim.

### 7.4 MCP Resources and Prompts (to demonstrate the full protocol)

- Resources: `filing://{accession}/press-release`, `company://{ticker}/profile` — read-only documents agents can fetch.
- Prompts: `evidence_pack_template`, `critique_checklist` — versioned prompt templates served by MCP, so prompt changes do not require agent redeploys in v1.1. In v1, agents may embed prompts and note this as a follow-up.

### 7.5 Tool-Output Safety

Tool output is **data, not instructions**. Agents are instructed to ignore instructional language inside filings, transcripts, or news ("ignore previous instructions", etc.). The Critic additionally flags any briefing claim that appears to originate from tool-output instruction rather than from a number.

## 8. Data Schemas (Pydantic v2 — the contract between agents)

All inter-agent payloads are validated Pydantic models. If validation fails, the task fails — the system never passes free-form LLM text between agents as its contract.

```python
class SourceRef(BaseModel):
    url: str
    publisher: str  # e.g. "SEC EDGAR", "Alphabet IR"
    retrieved_at: datetime
    excerpt: str | None = None

class Fact(BaseModel):
    id: str
    metric: str  # e.g. "total_revenue", "cloud_revenue", "gaap_eps"
    value: float
    unit: str  # "USD_B", "USD", "pct"
    period: str  # "Q3 2026", quarter end date ISO
    source: SourceRef
    verified: bool = False  # True only if Critic re-checked it

class EvidencePack(BaseModel):
    ticker: str
    company_name: str
    quarter_label: str
    quarter_end: date
    report_date: datetime
    status: Literal["REPORTED", "NOT_REPORTED_YET"]
    facts: list[Fact]
    guidance_verbatim: list[str] = []
    consensus: dict | None = None  # with source label + as_of
    price_reaction: dict | None = None
    missing: list[str] = []  # anything Scout could not find, stated plainly

class Claim(BaseModel):
    text: str
    value: float | None = None
    derivation: str  # e.g. "(127.6-102.3)/102.3 = 24.7%"
    evidence_ids: list[str]

class Analysis(BaseModel):
    ticker: str
    quarter_label: str
    verdict_draft: str
    claims: list[Claim]
    beat_miss: list[dict]  # metric, reported, consensus, diff, verdict
    drivers: list[str]
    risks_and_watch: list[str]

class Critique(BaseModel):
    verdict: Literal["PASS", "FAIL"]
    issues: list[dict]  # severity, claim_id, description, required_fix
    rechecked_facts: list[str]  # fact ids Critic independently verified

class Briefing(BaseModel):
    ticker: str
    quarter_label: str
    verdict: str
    table: list[dict]
    drivers: list[str]
    market_reaction: str
    guidance_and_watch: list[str]
    sources: list[SourceRef]
    disclaimer: str = "Informational only. Not investment advice."
    trace_id: str
```

## 9. End-to-End Flow — GOOGL Example

1. User: "How was Google's recent earnings?"
2. Orchestrator: resolve_ticker("Google") → GOOGL, Alphabet Inc. Note GOOG share class in profile, proceed with GOOGL filing (same Alphabet results).
3. A2A → Scout `collect_evidence {ticker: GOOGL}`. Scout calls filings-mcp `get_latest_earnings_filing` → 8-K, Q3 2026, reported 28 Oct 2026. Calls market-mcp `get_price_reaction` and estimates-news-mcp `get_consensus_estimates` + `get_earnings_calendar`. Returns EvidencePack with ~15–25 facts.
4. A2A → Analyst `analyse {evidence_pack}`. Analyst computes YoY, margins, beat/miss, drivers. Returns Analysis with claims + derivations.
5. A2A → Critic `critique {evidence_pack, analysis}`. Critic re-calls filings-mcp for revenue, EPS, Cloud, CapEx, and market-mcp for price move. Checks arithmetic and GAAP labels. Suppose it finds: Analyst wrote "EPS beat" — FAIL, blocker. Or Analyst omitted FCF negative — FAIL, major omission. Returns Critique.
6. If FAIL: Orchestrator → Analyst revision (max 2 loops) → Critic re-check.
7. A2A → Writer `write {approved_analysis}`. Writer renders Briefing, no new numbers.
8. Orchestrator returns Briefing + trace (A2A task graph, MCP calls, Critic verdicts, timings, token usage) to UI.

Total target: 45–90 seconds for a warm run, dominated by LLM calls, not tool calls.

## 10. LLM Layer

- Provider abstraction: a single `LLMClient` interface with OpenAI-compatible calls. Default in v1: OpenAI (or Azure OpenAI) via env config. Model choice is env-configurable per agent (e.g. stronger model for Critic, faster model for Writer) — document the choice, don't hardcode it in agent code.
- Structured output: every agent returns Pydantic-validated JSON. Free-form text is only allowed inside Writer's rendered prose, and even there numbers are templated from the Analysis.
- Temperature: Scout 0.0, Analyst 0.1, Critic 0.0, Writer 0.3.
- Token / cost budget per run: logged in trace. Target: <$0.50 per briefing on mid-tier models in v1; if exceeded, log a warning, do not silently switch models mid-run.
- No LLM call is allowed to "fill in" a missing fact. Missing → `missing[]` → briefing says so.

## 11. Observability and Trace View

Every run gets a `trace_id`. The trace records, in order:

- A2A tasks: agent, start/end, state, artifact id
- MCP calls: server, tool, inputs (redacted for secrets — there are none in v1, but the redaction hook exists), latency, cache hit/miss
- LLM calls: agent, model, tokens in/out, latency
- Critic verdicts and loop count
- Final briefing hash (so a re-run can be compared)

UI trace view: a vertical timeline, expandable per agent, with failed Critic checks highlighted in red and passed checks in green. This view is the portfolio centrepiece — it is what a reviewer clicks first after the briefing itself.

Logs: structured JSON to stdout (so Docker logs work). No user queries logged with personal data beyond the ticker asked about.

## 12. Evaluation — How We Prove It Works

Golden fixtures (checked into `tests/fixtures/`):

| Fixture | Why it matters |
|---|---|
| GOOGL Q3 2026 | Messy quarter: operating beat + GAAP EPS miss + FCF negative. Critic must catch GAAP/operating confusion. |
| NVDA (latest quarter at test time) | High-expectation stock: beat/miss vs whisper vs consensus distinction. |
| AAPL (latest quarter) | Segment mix (iPhone vs Services) and buyback / EPS nuance. |
| MSFT (latest quarter) | Cloud (Azure) growth vs guidance nuance. |
| Ticker with no recent earnings (e.g. ask during quiet period) | Scout must return NOT_REPORTED_YET, not hallucinate. |
| Ambiguous input ("Apple" vs "Apple Hospitality" style collisions, GOOG vs GOOGL) | Orchestrator must clarify or document its resolution rule. |
| Deliberately corrupted Analyst output (test harness injects a wrong YoY %) | Critic must FAIL it. This is a unit test for the Critic, not a hope. |

Pass criteria for v1 launch:

- 100% of headline numbers in golden briefings match the filing (Critic re-check, automated).
- 0 uncited numbers in any golden briefing.
- Critic catches 100% of injected arithmetic errors in the test harness.
- Median end-to-end time < 90s on golden set.
- Every run produces a complete trace, including failures.

## 13. Security, Safety, and Disclaimers

- MCP tools are read-only; the codebase should fail CI if a write tool is added without a security review note.
- No API keys in code, prompts, or traces. Keys via env / Docker secrets only.
- Tool output treated as data (Section 7.5). Prompt-injection test fixtures in `tests/security/` (a fake filing containing instructional text) must not change the briefing's numbers.
- Financial disclaimer on every briefing and on the README: informational only, not investment advice, verify against the filing before acting.
- Rate limiting: SEC EDGAR requires a User-Agent with contact; respect it. Cache filings. Do not hammer free price APIs in loops.

## 14. Deployment — Local First, Publishable Second

Docker Compose services (v1):

```
orchestrator:8000
scout:8001
analyst:8002
critic:8003
writer:8004
filings-mcp:8101
market-mcp:8102
estimates-news-mcp:8103
ui:8501 (Streamlit)
```

- Each agent and MCP server is its own container with its own Dockerfile (shared base image).
- Env: `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL_*` per agent, `EDGAR_USER_AGENT`, `TRACE_LEVEL`.
- Local dev without Docker: each service runnable via `uv run` / `python -m`, with a `justfile` or `Makefile` for common commands.
- CI: GitHub Actions — lint (ruff), typecheck (mypy, at least on schemas), unit tests (schemas, Critic arithmetic, ticker resolution), fixture test for GOOGL (mocked MCP responses so CI does not depend on live EDGAR).
- README must include: architecture diagram, 60-second demo (GIF or screenshots), how to run, how the Critic loop works, known limitations (consensus source), and the GOOGL worked example.

## 15. Repository Structure

```
agent-mesh-earnings/
├── README.md
├── ARCHITECTURE.md            # this file
├── docker-compose.yml
├── Makefile
├── pyproject.toml
├── apps/
│   ├── ui/                    # Streamlit: query box, briefing, trace view
│   └── orchestrator/          # FastAPI + A2A client + task graph
├── agents/
│   ├── scout/
│   ├── analyst/
│   ├── critic/
│   └── writer/
│   └── common/                # A2A client/server helpers, LLM client, schemas
├── mcp_servers/
│   ├── filings/
│   ├── market/
│   └── estimates_news/
├── schemas/                   # Pydantic models shared by agents (EvidencePack, etc.)
├── tests/
│   ├── fixtures/              # GOOGL Q3 2026 + others, mocked MCP responses
│   ├── unit/
│   ├── integration/           # full mesh run against mocks
│   └── security/              # prompt-injection fixtures
└── docs/
    ├── demo-script.md
    └── decisions/             # ADRs: A2A library choice, MCP transport, consensus source
```

## 16. 7-Day Build Plan

**Day 1 — Contracts first.** Schemas (Section 8), Agent Cards, repo skeleton, Docker Compose with hello-world services. Acceptance: `docker compose up` shows all 9 services healthy, cards served.

**Day 2 — MCP servers.** filings-mcp against live EDGAR, market-mcp via yfinance, estimates-news-mcp with labelled consensus fallback. Acceptance: MCP Inspector can call each tool for GOOGL and return real filing data.

**Day 3 — Scout + Analyst.** Scout EvidencePack for GOOGL Q3 2026 matches the fixture numbers. Analyst computes YoY/margin/beat-miss correctly on the fixture. Acceptance: golden fixture test passes.

**Day 4 — Critic loop.** Critic re-queries MCP, catches injected errors, loops Analyst max 2 times. Acceptance: corrupted-Analyst test fails in Critic, clean Analyst passes.

**Day 5 — Writer + Orchestrator + UI.** End-to-end query → briefing → trace view in Streamlit. Acceptance: "How was Google's recent earnings?" returns a cited briefing in <90s warm.

**Day 6 — Evals, security, polish.** Run full golden set, add prompt-injection fixtures, add disclaimer, record demo GIF/screenshots, write README with architecture diagram.

**Day 7 — Publish.** Push to GitHub, verify a fresh clone + `docker compose up` works with only an LLM key, write the launch post draft (for the user to post, not auto-posted). Acceptance: a stranger can reproduce the GOOGL briefing.

## 17. Open Decisions to Lock Before Day 1

1. **LLM provider / model:** OpenAI vs Anthropic vs Azure OpenAI. Recommendation: OpenAI-compatible interface, default `gpt-5-mini`-class for Scout/Writer and a stronger model for Critic, all env-configurable. Do not let the provider choice leak into agent logic.
2. **A2A library:** `a2a-sdk` (Python, Google) vs Google ADK (which bundles A2A + MCP toolsets). Recommendation: start with `a2a-sdk` + FastAPI so A2A and MCP remain visibly separate layers — that separation is the learning goal. Revisit ADK as a v1.1 comparison note.
3. **MCP transport:** Streamable HTTP for the mesh; stdio only for Inspector testing. Lock this to avoid mixing transports mid-build.
4. **Consensus source for v1:** label the free source used, show as-of date, and show a range where vendors disagree. Do not present a single consensus number as authoritative if the source is weak.
5. **UI scope:** Streamlit in v1 (fast, Python-only). A Next.js UI is a v1.1 option, not a v1 blocker.

## 18. Future Extensions (not v1, listed so the README can promise a roadmap)

- Follow-up questions in the same session ("How did Cloud do vs last quarter?") with session memory.
- Peer comparison agent (e.g. GOOGL Cloud vs MSFT Azure vs AMZN AWS in the same quarter).
- Guidance tracker: what management promised last quarter vs what was delivered.
- Charts for segment growth and margin trend.
- Agent registry: discover agents dynamically instead of env-configured URLs.
- Voice input / briefing narration.
- More tickers: earnings calendar watch — "alert me when NVDA reports."

---

*End of spec v1.0. Next step after approval: lock the 5 decisions in Section 17, then start Day 1 (contracts + repo skeleton).*
