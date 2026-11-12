#!/usr/bin/env python3
"""Stamp same-origin asset URLs in web/index.html with content hashes.

Why: Wave-3 (Nov 12, 2026) shipped a new app.js against a cached
pre-Wave-3 styles.css in Tej's browser — the week view rendered with
no .wk-* rules at all (light panel instead of the dark one, days
stacked, labels and tiles inline, content-sized tiles). The HTML
referenced bare `styles.css` / `app.js`, so a returning browser was
free to serve the old stylesheet with the new script.

The fix: `styles.css?v=<sha256[:8]>`, `app.js?v=<sha256[:8]>`,
`favicon.svg?v=<sha256[:8]>`. A changed file gets a new URL, so the
browser always fetches the matching pair; an unchanged file keeps
its cached copy. Idempotent: re-running with unchanged files leaves
index.html byte-identical.

Run before every push (the suite enforces the stamps are current:
tests/unit/test_asset_cache_busting.py). The watch script's
fingerprint curls app.js without a query — the file still exists
at that URL, so it is unaffected.
"""
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "web" / "index.html"
ASSETS = {"styles.css": ROOT / "web" / "styles.css",
          "app.js": ROOT / "web" / "app.js",
          "favicon.svg": ROOT / "web" / "favicon.svg"}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()[:8]


def main():
    html = INDEX.read_text()
    changed = False
    for name, path in ASSETS.items():
        tag = digest(path)
        # Match the bare URL or an already-stamped one, in an
        # href/src attribute only.
        pattern = re.compile(r'((?:href|src)=")' + re.escape(name) + r'(?:\?v=[0-9a-f]{8})?"')
        new_html, n = pattern.subn(r'\1' + name + '?v=' + tag + '"', html)
        if n == 0:
            print(f"no reference to {name} in index.html", file=sys.stderr)
            return 1
        if new_html != html:
            changed = True
            html = new_html
        print(f"{name}: v={tag} ({n} reference{'s' if n > 1 else ''})")
    if changed:
        INDEX.write_text(html)
        print("index.html updated")
    else:
        print("index.html already current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
