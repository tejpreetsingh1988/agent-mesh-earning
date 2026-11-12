"""Print-scope guard (Batch 70): the Batch 66 month-grid and Batch 67
week-view calendar rules must live at top level, never inside
`@media print`.

What happened (Nov 12, 2026): the `@media print` block (line 396)
was never closed before the calendar blocks were added, so all 33
`.wk-*` rules — the dark panel, the 5-column grid, the orange
headers, the 52px tiles, the side-by-side halves — were print-only
and the calendar rendered unstyled on screen in every browser, even
after a hard refresh. The file still parsed cleanly and the braces
still balanced, so only a scope check catches it.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CSS = ROOT / "web" / "styles.css"
CAL = re.compile(r"\.(wk|cal)-[a-z-]+")


def _stripped(css):
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.sub(r'"[^"]*"', '""', css)
    css = re.sub(r"'[^']*'", "''", css)
    return css


def _print_spans(css):
    """(start, end) char spans of every @media print block body."""
    spans = []
    for m in re.finditer(r"@media\s+print\s*\{", css):
        depth = 1
        i = m.end()
        while i < len(css) and depth:
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
            i += 1
        spans.append((m.end(), i - 1))
    return spans


def test_no_calendar_rules_inside_print():
    css = _stripped(CSS.read_text())
    for start, end in _print_spans(css):
        body = css[start:end]
        assert not CAL.search(body), (
            "calendar rules trapped inside @media print: "
            + ", ".join(sorted(set(CAL.findall(body)))[:5])
        )


def test_week_rules_are_top_level():
    css = _stripped(CSS.read_text())
    spans = _print_spans(css)

    def in_print(pos):
        return any(s <= pos < e for s, e in spans)

    top = [m for m in CAL.finditer(css)
           if m.group(0).startswith(".wk-") and not in_print(m.start())]
    assert len(top) >= 30, (
        f"only {len(top)} top-level .wk- selectors; "
        "the week view may be trapped in a media block again"
    )
