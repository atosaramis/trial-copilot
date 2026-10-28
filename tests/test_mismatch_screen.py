"""Mismatch-check screen: main view, lead demo first, saved playback with no API call, plain-words
labels, distinct "check this" flags, validation numbers taken from the saved file, no blame words."""
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import cache, main, mismatch_view
from app.framing import BANNED_BLAME

ROOT = Path(__file__).resolve().parents[1]
LEAD = "NCT02720510"


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "CACHE", tmp_path)
    monkeypatch.delenv("TRIAL_COPILOT_LIVE", raising=False)
    monkeypatch.delenv("META_API_KEY", raising=False)
    return TestClient(main.app)


def test_mismatch_is_the_main_view_and_leads_with_myeloma(client):
    html = client.get("/").text
    assert re.search(r'class="tab on\s*" id="tab-mismatch"', html)
    assert 'id="mismatch"' in html and 'id="mismatch-validation"' in html
    first_chip = re.search(r'class="chip on">([^<]+)<span class="rid"> (NCT\d+)', html)
    assert first_chip and first_chip.group(2) == LEAD
    assert "approximately 20 centers" in html and "Saved result · no API call" in html


def test_secondary_tabs_kept(client):
    assert 'id="registry-risk"' in client.get(f"/?tab=audit&demo={LEAD}").text
    assert "Brier score" in client.get("/?tab=validation").text
    assert 'id="mismatch"' in client.get("/?tab=nonsense").text


def test_saved_playback_makes_no_api_call(client, monkeypatch):
    import openai

    def boom(*a, **k):
        raise AssertionError("no API call on the mismatch screen")
    monkeypatch.setattr(openai, "OpenAI", boom)
    monkeypatch.setattr(main, "_live", boom)
    for nct in cache.demos():
        r = client.get(f"/?tab=mismatch&demo={nct}")
        assert r.status_code == 200 and nct in r.text
    assert main.live_status()["enabled"] is False


def test_every_demo_and_card_part_renders(client):
    data = cache.mismatch()
    assert [d["nct_id"] for d in data["demos"]][0] == LEAD and len(data["demos"]) == 5
    html = client.get(f"/?tab=mismatch&demo={LEAD}").text
    for needle in ("Protocol says", "ClinicalTrials.gov record said", "Jan 2017", "Jan 2020", "Jan 2023",
                   "The registry never changed", "The documents disagree", "quote verified, p.9",
                   "Prot_000.pdf#page=9", "matches the registry history"):
        assert needle in html, needle


def test_check_this_flags_are_distinct_and_explained(client):
    html = client.get("/").text
    n_flag = html.count('class="flag-check"')
    n_check_cards = html.count('class="mm mm-check"')
    assert n_flag == n_check_cards >= 3
    assert "The protocol gives a maximum" in html and "The agent and the registry history disagree" in html
    assert "The registry went past the protocol" in html


def test_card_logic_flags_doubtful_and_disagreeing_cases():
    base = {"field": "sites", "protocol_value": 20, "registry_value": 5, "severity": "high", "traps": [],
            "page": 3, "quote": "q", "timeline": [{"year": "2017", "value": 5}, {"year": "2020", "value": 9}],
            "auto": "never_changed", "agent": None}
    assert not mismatch_view.card(base, None)["check"]
    assert mismatch_view.card(dict(base, traps=["upper_bound"]), None)["check"]
    ag = {"verdict": "registry_lagging", "explanation": "e", "citations": [], "dropped": 0, "agrees": False}
    c = mismatch_view.card(dict(base, agent=ag), "https://x/p.pdf")
    assert c["check"] and c["page_url"] == "https://x/p.pdf#page=3" and c["timeline"][1]["changed"]


def test_validation_numbers_come_from_the_saved_file(client):
    v = cache.mismatch()["validation"]["candidates"]["v3"]
    html = client.get("/").text
    assert f"{v['agree']} of {v['settled']}" in html
    assert f"{v['quotes_kept']} of {v['quotes_offered']}" in html
    assert f"{v['extraction_error']} of {v['mismatches']}" in html
    assert "Most of the agreement gain is bookkeeping" in html and "No held-out test" in html
    tpl = (ROOT / "app" / "templates" / "mismatch.html").read_text()
    for typed in ("222", "85%", "50 of 59", "148", "19%"):
        assert typed not in tpl, typed


def test_saved_file_holds_design_fields_only():
    text = (ROOT / "demo_cache" / "mismatch.json").read_text()
    for bad in ("status", "why_stopped", "Terminated", "label_poor", "outcome", "/workspace", "/home/"):
        assert bad not in text, bad


def test_no_blame_words_on_any_screen(client):
    pages = [client.get(u).text.lower() for u in
             ("/", f"/?tab=audit&demo={LEAD}", "/?tab=validation", *[f"/?demo={n}" for n in cache.demos()])]
    files = [p.read_text().lower() for p in [*(ROOT / "app" / "templates").glob("*.html"),
                                             ROOT / "app" / "mismatch_view.py", ROOT / "README.md"]]
    for text in pages + files:
        for w in BANNED_BLAME:
            assert not re.search(r"\b" + re.escape(w) + r"\b", text), w
