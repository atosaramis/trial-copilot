"""Primary-outcome triage view: main tab, saved data only, neutral wording, short quotes with
page links to ClinicalTrials.gov (never rehosted), funnel numbers consistent, no API call."""
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import cache, main, outcome_view
from app.framing import BANNED_BLAME, BANNED_FRAMING

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "demo_cache" / "outcomes.json"
# Words that state a conclusion the documents can't support on their own.
LOADED = ["switched", "switching", "fraud", "cheat", "cheated", "manipulated", "hid", "hidden", "cover-up",
          "cherry-picked", "p-hacking", "guilty", "deceptive", "misled", "misleading"]


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "CACHE", tmp_path)
    monkeypatch.delenv("TRIAL_COPILOT_LIVE", raising=False)
    monkeypatch.delenv("META_API_KEY", raising=False)
    return TestClient(main.app)


def data():
    return json.loads(DATA.read_text())


def all_quotes(d):
    for c in d["cases"]:
        for x in c["docs"]:
            yield c["nct"], x
    for s in d["shortlist"] + d["probable"] + d["safety_pk"] + d["explained"]:
        for q in s["quotes"]:
            yield s["nct"], q
        if s["explaining"]:
            yield s["nct"], s["explaining"]


def test_triage_is_the_main_view(client):
    html = client.get("/").text
    assert re.search(r'class="tab on\s*" id="tab-outcomes"', html)
    for sid in ("outcomes", "outcome-funnel", "lead-case", "cleared-case", "agreement", "shortlist", "outcome-limits"):
        assert f'id="{sid}"' in html, sid
    assert "REMIT-Sita" in html and "JUNIPER" in html
    assert "not medical advice" in html.lower() and "not a regulatory finding" in html.lower()


def test_no_api_call(client, monkeypatch):
    import openai

    def boom(*a, **k):
        raise AssertionError("no API call on the triage screen")
    monkeypatch.setattr(openai, "OpenAI", boom)
    monkeypatch.setattr(main, "_live", boom)
    assert client.get("/?tab=outcomes").status_code == 200


def test_funnel_numbers_shrink_and_match_the_counts():
    d = data()
    ns = [f["n"] for f in d["funnel"]]
    assert ns[:5] == [1436, 1015, 234, 73, 33]
    assert all(a > b for a, b in zip(ns, ns[1:]))
    assert sum(d["triage"].values()) == ns[1]
    assert sum(d["spark_calls"].values()) == ns[3]
    c = d["wonder_counts"]
    assert sum(c.values()) == ns[4]
    assert ns[5] == ns[4] - c["explained"] == len(d["shortlist"]) + len(d["probable"]) + len(d["safety_pk"])
    assert len(d["shortlist"]) == ns[6] and len(d["explained"]) == c["explained"]
    # funnel stages plus the $0.02 vision transcription of one scanned analysis plan
    assert d["total_cost"] == round(sum(f["cost"] for f in d["funnel"]) + 0.02, 2)


def test_every_quote_is_verified_short_and_linked_to_ctgov_page():
    d = data()
    qs = list(all_quotes(d))
    assert len(qs) >= 100
    for nct, q in qs:
        assert q["verified"] is True
        assert len(q["quote"]) <= 280, (nct, q["quote"][:40])
        assert re.fullmatch(rf"https://cdn\.clinicaltrials\.gov/large-docs/{nct[-2:]}/{nct}/[A-Za-z_0-9]+\.pdf#page={q['page']}", q["url"])


def test_lead_timeline_orders_protocol_before_start_and_change_after_it():
    lead = next(c for c in data()["cases"] if c["role"] == "lead")
    assert lead["nct"] == "NCT02623998"
    tl = lead["timeline"]
    assert [e["date"] for e in tl] == sorted(e["date"] for e in tl)
    proto = next(e for e in tl if e["kind"] == "protocol")
    change = next(e for e in tl if e.get("first_change"))
    assert proto["date"] < lead["dates"]["start"] < change["date"]
    assert lead["would_change"]


def test_cleared_case_has_a_dated_amendment_before_the_registry_change():
    c = next(c for c in data()["cases"] if c["role"] == "cleared")
    amend = next(e for e in c["timeline"] if e["kind"] == "amendment")
    change = next(e for e in c["timeline"] if e.get("first_change"))
    assert amend["date"] < change["date"] and amend["date"] < c["dates"]["primary_completion"]


def test_no_pdf_rehosting_and_no_local_paths(client):
    text = DATA.read_text()
    for bad in ("/workspace", "/home/", "file://", "\\f"):
        assert bad not in text
    html = client.get("/").text
    pdf_links = re.findall(r'href="([^"]+\.pdf[^"]*)"', html)
    assert pdf_links and all(u.startswith("https://cdn.clinicaltrials.gov/") for u in pdf_links)


def test_neutral_wording(client):
    visible = re.sub(r"<[^>]+>", " ", client.get("/").text)
    pages = [visible.lower(), DATA.read_text().lower(),
             re.sub(r"<[^>]+>", " ", (ROOT / "app" / "templates" / "outcomes.html").read_text()).lower(),
             re.sub(r"<[^>]+>", " ", (ROOT / "app" / "templates" / "outcome_case.html").read_text()).lower(),
             (ROOT / "scripts" / "build_outcome_view.py").read_text().lower()]
    for text in pages:
        for w in LOADED + BANNED_BLAME + BANNED_FRAMING:
            assert not re.search(r"\b" + re.escape(w) + r"\b", text), w


def test_ai_checked_label_and_stale_panel_gone(client):
    html = client.get("/").text
    assert "not expert-verified" in html and "Not a prevalence estimate" in html
    mm = client.get("/?tab=mismatch").text
    assert "No held-out test" not in mm and "AI-adjudicated" in mm


def test_axis_positions_in_range():
    ctx = outcome_view.context(cache.outcomes())
    for c in (ctx["lead"], ctx["cleared"]):
        assert all(2 <= e["pos"] <= 98 for e in c["axis"])
    assert outcome_view.nice_date("2019-11-26") == "Nov 26, 2019" and outcome_view.nice_date("2016-07") == "Jul 2016"


def test_static_export_leads_with_triage(tmp_path, monkeypatch):
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import export_static
    monkeypatch.setattr(sys, "argv", ["export_static.py", "--out", str(tmp_path)])
    export_static.main()
    index = (tmp_path / "index.html").read_text()
    assert 'id="lead-case"' in index and 'href="mismatch.html"' in index
    for p in tmp_path.glob("*.html"):
        t = p.read_text()
        assert 'name="robots" content="noindex' in t, p.name
        assert not re.findall(r'(?:href|src)="/(?!/)', t), p.name
    assert not list(tmp_path.rglob("*.pdf"))


def test_no_inline_styles_or_scripts_in_triage_templates():
    for name in ("outcomes.html", "outcome_case.html", "static_site/outcomes_page.html", "static_site/nav.html"):
        t = (ROOT / "app" / "templates" / name).read_text()
        assert "style=" not in t and "<script" not in t, name


def test_wonder_stage_names_its_model_and_cost():
    d = data()
    stage = d["funnel"][5]
    assert stage["who"] == "Muse Wonder 1.0" and 5 < stage["cost"] == d["wonder_cost"] < 13
    assert d["funnel"][6]["who"] == "Code" and d["funnel"][6]["cost"] == 0
    assert d["quotes"]["kept"] <= d["quotes"]["offered"]


def test_shortlist_follows_wonder_verdicts_and_keeps_the_lead_first():
    d = data()
    short = d["shortlist"]
    assert short[0]["nct"] == "NCT02623998"
    assert all(s["verdict"] in ("needs_review", "timing_unsettled", "possible_data_entry_error") for s in short)
    assert not any(s["safety_pk"] for s in short)
    assert all(s["verdict"] == "probable" for s in d["probable"])
    assert all(s["verdict"] == "explained" and s["explaining"] for s in d["explained"])
    for s in short + d["probable"] + d["safety_pk"] + d["explained"]:
        assert s["reason"] and s["would_change"], s["nct"]
    lead = next(c for c in d["cases"] if c["role"] == "lead")
    cleared = next(c for c in d["cases"] if c["role"] == "cleared")
    assert lead["wonder"]["verdict"] == "needs_review" and cleared["wonder"]["verdict"] == "explained"


def test_agreement_numbers_match_the_case_data():
    d = data()
    a = d["agreement"]
    every = {s["nct"]: s for s in d["shortlist"] + d["probable"] + d["safety_pk"] + d["explained"]}
    earlier = {n: s for n, s in every.items() if s["earlier"]}
    assert len(earlier) == a["n"] == 12
    def grp(v):
        return "holds_up" if v in ("needs_review", "timing_unsettled", "possible_data_entry_error") else v
    same = [n for n, s in earlier.items() if grp(s["verdict"]) == s["earlier"]]
    assert len(same) == a["three_groups"]
    assert sum((grp(s["verdict"]) == "explained") == (s["earlier"] == "explained") for s in earlier.values()) == a["explained_or_not"]
    assert {x["nct"] for x in a["differs"]} == set(earlier) - set(same)
    assert -1 <= a["kappa"] <= 1


def test_agreement_is_worded_as_ai_adjudicated(client):
    html = client.get("/").text
    sec = html[html.index('id="agreement"'):html.index('id="shortlist"')]
    assert "AI-adjudicated" in sec and "not expert-verified" in sec
    assert f'{data()["agreement"]["explained_or_not"]} of 12' in sec
    assert "Muse Wonder 1.0" in html[html.index('id="outcome-funnel"'):html.index('id="lead-case"')]
