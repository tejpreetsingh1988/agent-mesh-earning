# ADR 020 — Single search: company search only, ticker box removed

## Status
Accepted Nov 2, 2026, at Tej's direction ("remove Ticker
search as well").

## Decision
The homepage has one search: the company-name search box
(ADR 018), relabeled "Search by company name or ticker".
The ticker input, Get briefing button, and Try chips are
removed from `web/index.html`, and the briefing's ticker
now lives in a `currentTicker` variable in `web/app.js`,
set by the suggestion click that starts the run. The log
download filename uses it. No other behavior changes.

## Why ticker lookup still works
Each company page carries "Ticker: X" in plain text, so a
ticker typed into the search box matches its company page
by keyword. The ticker box was redundant once name search
existed, and two searches invited confusion about which one
to use.

## Verification
Live check after deploy: no ticker input on the homepage;
typing "Intel" still yields INTC and starts a briefing, and
typing "GOOGL" yields the Alphabet page.
