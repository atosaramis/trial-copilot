"""CI-style check: banned framing words must not appear in the app, README or templates
(build spec section 1)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from app.framing import BANNED_FRAMING as BANNED  # noqa: E402

LIST_FILE = ROOT / "app" / "framing.py"  # the list itself
SCAN_SUFFIXES = {".py", ".txt", ".md", ".html", ".jinja", ".j2", ".js", ".css", ".json"}


def _files():
    yield ROOT / "README.md"
    for d in ["app", "docs"]:
        for p in (ROOT / d).rglob("*"):
            if p.is_file() and p.suffix in SCAN_SUFFIXES and "__pycache__" not in p.parts and p != LIST_FILE:
                yield p


def test_no_banned_words():
    hits = []
    for p in _files():
        text = p.read_text(errors="replace").lower()
        for w in BANNED:
            if re.search(r"\b" + re.escape(w) + r"\b", text):
                hits.append(f"{p.relative_to(ROOT)}: {w}")
    assert not hits, "banned words found: " + "; ".join(hits)


def test_list_unchanged():
    assert len(BANNED) == 12 and "treatment recommendation" in BANNED
