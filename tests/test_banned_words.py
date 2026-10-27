"""CI-style check: banned framing words must not appear in the app, README or templates
(build spec section 1)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BANNED = ["clinical decision support", "patient recommendation", "treatment guidance",
          "treatment recommendation", "diagnose", "diagnosis", "prescribe",
          "patient safety advisor", "chat with your pdf", "ask the protocol",
          "ai predicts whether your trial will fail", "oracle"]
SCAN_SUFFIXES = {".py", ".txt", ".md", ".html", ".jinja", ".j2", ".js", ".css", ".json"}


def _files():
    yield ROOT / "README.md"
    for d in ["app", "docs"]:
        for p in (ROOT / d).rglob("*"):
            if p.is_file() and p.suffix in SCAN_SUFFIXES and "__pycache__" not in p.parts:
                yield p


def test_no_banned_words():
    hits = []
    for p in _files():
        text = p.read_text(errors="replace").lower()
        for w in BANNED:
            if re.search(r"\b" + re.escape(w) + r"\b", text):
                hits.append(f"{p.relative_to(ROOT)}: {w}")
    assert not hits, "banned words found: " + "; ".join(hits)
