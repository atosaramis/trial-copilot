"""Saved demo results, keyed by the protocol PDF's SHA-256 (build spec section 2, demo safety).

The 5 demo trials replay their saved trial card, search trace, risk numbers and memo, so the demo
runs with no API call. The Jan 2020 registry outcome sits in a separate file that only the
reveal button reads.
"""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = ROOT / "demo_cache"
REVEAL_FILE = DEMO_DIR / "reveal.json"


@lru_cache(maxsize=1)
def demos() -> dict[str, dict]:
    """nct_id -> saved demo, lead demo first."""
    order = ["NCT02720510", "NCT01857271", "NCT02735980", "NCT02155660", "NCT02760602"]
    found = {p.stem: json.loads(p.read_text()) for p in DEMO_DIR.glob("NCT*.json")}
    return {k: found[k] for k in order if k in found} | {k: v for k, v in found.items() if k not in order}


def demo_by_sha(sha: str) -> dict | None:
    return next((d for d in demos().values() if d["pdf_sha256"] == sha), None)


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def reveal(nct_id: str) -> dict | None:
    """What the registry showed on Jan 1, 2020. Display only; never passed to a model."""
    if nct_id not in demos():
        return None
    return json.loads(REVEAL_FILE.read_text()).get(nct_id)


MISMATCH_FILE = DEMO_DIR / "mismatch.json"


@lru_cache(maxsize=1)
def mismatch() -> dict | None:
    """Saved mismatch-check results for the demos, tuning-set examples and validation numbers
    (built offline by scripts/build_mismatch_view.py; no API call). Design fields only."""
    try:
        return json.loads(MISMATCH_FILE.read_text())
    except (OSError, ValueError):
        return None
