"""Direct (in-process) MCP tool calls — no HTTP hop.

Same (server, tool, args) contract as mesh.mcp_client.make_client():
``direct_call(server, tool, args) -> dict``. The difference is that
each tool is the underlying mesh function itself, not an HTTP call
to a sibling MCP service.

Use it wherever there is no MCP service to call: the Cloudflare
Scout Worker proof (a Worker has no sibling services) and any
single-process host (e.g. Streamlit Cloud) that runs the pipeline
in-process. Tool behaviour is identical either way — the functions
below are the same ones the MCP servers dispatch to — so a pack
built through direct_call and a pack built through HTTP differ only
in transport, never in numbers.

Market tools degrade the same way they do over HTTP: if yfinance
is not installed (the Scout Worker proof v1 deliberately omits it
from its dependencies), the import raises inside Scout's try blocks
and Scout records the step in `missing` instead of failing. EDGAR,
consensus (Nasdaq keyless + GOOGL range), and transcript are
stdlib-only and carry the pack on their own.
"""
from . import edgar, edgar_facts, market, news, transcript

_TOOLS = {
    "filings": {
        "get_company_facts": edgar.get_company_facts,
        "get_filing_facts": edgar_facts.get_filing_facts_for_ticker,
        "get_latest_earnings_filing": edgar.get_latest_earnings_filing,
        "get_filing_text": edgar.get_filing_text,
        "get_transcript_excerpt": transcript.fetch_transcript,
        "list_recent_filings": edgar.list_recent_filings,
    },
    "market": {
        "get_price_reaction": market.get_price_reaction,
        "get_quarterly_history": market.get_quarterly_history,
        "get_company_profile": market.get_company_profile,
    },
    "estimates_news": {
        "get_consensus_estimates": news.get_consensus_estimates,
        "get_earnings_calendar": news.get_earnings_calendar,
        "get_recent_news": news.get_recent_news,
    },
}


def direct_call(server: str, tool: str, args: dict | None = None) -> dict:
    """Call one MCP tool in-process. Raises ValueError on unknown tool."""
    try:
        fn = _TOOLS[server][tool]
    except KeyError:
        raise ValueError(f"Unknown MCP tool: {server}/{tool}") from None
    return fn(**(args or {}))
