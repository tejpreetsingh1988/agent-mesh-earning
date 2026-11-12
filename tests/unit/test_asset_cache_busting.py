"""Cache-busting stamps (Batch 69): index.html must reference the
versioned asset URLs, and each stamp must equal the file's current
content hash — otherwise a returning browser can serve a stale
stylesheet with a new script (Wave-3, Nov 12, 2026: the week view
rendered with no .wk-* rules at all). Run scripts/stamp-assets.py
before a push; this test is the enforcement."""
import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
INDEX = ROOT / "web" / "index.html"
ASSETS = ["styles.css", "app.js", "favicon.svg"]


def digest(name):
    return hashlib.sha256((ROOT / "web" / name).read_bytes()).hexdigest()[:8]


def test_stamps_match_content_hashes():
    html = INDEX.read_text()
    for name in ASSETS:
        m = re.search(r'(?:href|src)="' + re.escape(name) + r'\?v=([0-9a-f]{8})"', html)
        assert m, f"{name} has no ?v= stamp in index.html"
        assert m.group(1) == digest(name), (
            f"{name} stamp {m.group(1)} != current hash {digest(name)} "
            "(run scripts/stamp-assets.py)"
        )


def test_no_bare_asset_references():
    html = INDEX.read_text()
    for name in ASSETS:
        # A bare reference (no ?v=) must not remain in an href/src.
        assert not re.search(r'(?:href|src)="' + re.escape(name) + r'"', html), (
            f"bare {name} reference left in index.html"
        )
