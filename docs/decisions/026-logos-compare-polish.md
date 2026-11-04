# ADR 026 — Company logos + compare-box polish

## Logos

Source: Parqet's ticker-keyed logo endpoint
`https://assets.parqet.com/logos/symbol/{TICKER}`.
Chosen because it needs no key and no per-company
domain mapping (Clearbit and favicon services both
need domains for all 109 companies), returns crisp
SVG, and covers every directory ticker tested
(AAPL, DDOG, RBLX, KR, SO, NEE, MAR, HLT, CMG,
DUK all HTTP 200). An unknown ticker 404s with an
empty body, so `onerror` reliably swaps in a muted
initials tile — the page never shows a broken-image
icon. Logos appear on search suggestion chips,
compare suggestion chips, the briefing header, and
both comparison verdict blocks. They are decorative
(`alt=""`, `loading="lazy"`); the ticker text always
carries the meaning, so a missing logo loses nothing.

## Compare-box polish

The box previously rendered a bare label, an
unstyled browser-default input, and a hint with no
separation from the quarter picker above it — that
is what read as ugly. Fixed inside the existing
system, no new colors: the box is now a separated
section (top border, padding), its input matches
the search input's height/border/radius but without
the search input's uppercase transform (company
names must not be uppercased), the comparison's
`h4` headings are small muted subheads, the
quarters note is small muted text, and each verdict
is a bordered card with a logo + ticker head row.
