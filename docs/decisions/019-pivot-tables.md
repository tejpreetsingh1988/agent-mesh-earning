# ADR 019 — Pivot tables: quarters as columns, one table per metric

## Status
Accepted Nov 2, 2026, from Tej's screenshot feedback on the
Scout card (Mastercard Q3 2026): the long one-row-per-fact
list is unreadable at eight quarters of history.

## Decision
- Scout card: facts pivot into one table per metric — a
  Revenue table, an Operating Income table, an EPS table,
  then any other metrics alphabetically. Quarters run across
  the top as columns (Q1 2026, Q2 2026, Q3 2026, ...), derived
  from each fact's period end month (01–03 Q1, 04–06 Q2,
  07–09 Q3, 10–12 Q4). Each table has a colored dot + unit
  badge (revenue green, operating income blue, EPS violet,
  other zinc); the latest quarter column is tinted and bold.
  Tables are `<details open>` so any metric collapses with
  one click. Hovering a value shows its exact figure, unit,
  and derived status as a tooltip.
- Derived fiscal-Q4 rows (fiscal-year total minus 9-month
  year-to-date) carry a † with a footnote, since they are
  computed, not filed.
- Analyst card and the briefing record: claims become
  blocks instead of a cramped three-column table — claim
  text, a colored value pill (growth blue, margin violet,
  EPS/consensus amber, price teal), derivation as muted
  subtext. The briefing record uses the same blocks so it
  matches what the card showed.
- Deliberately NOT built: a YoY delta chip on the Scout
  table. Growth math belongs to the Analyst; a second
  frontend-computed figure could disagree with it by
  rounding, and the file's rule is that the frontend
  computes no numbers — every value shown is a streamed
  fact or claim, rounded to one decimal as before.

## Verification
Pure-function check in Node (app.js loaded with DOM stubs):
quarter columns in order, revenue before operating income
before EPS, derived † present, latest column marked, unit
badges present. Live visual check via a Mastercard briefing
screenshot follows the upload.
