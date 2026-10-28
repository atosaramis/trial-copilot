"""App tests: saved demos replay with no API call, live mode is gated, the reveal stays out of model code,
and the browser slider maths matches app/risk.py."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import cache, main, risk

ROOT = Path(__file__).resolve().parents[1]
LEAD = "NCT02720510"
DISCLAIMER = "Study-planning tool for trial sponsors, not medical advice."


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "STEP_DELAY", 0.0)
    monkeypatch.setattr(main, "CACHE", tmp_path)
    monkeypatch.delenv("TRIAL_COPILOT_LIVE", raising=False)
    return TestClient(main.app)


def _events(client, html):
    job = re.search(r'data-job="([0-9a-f]+)"', html).group(1)
    with client.stream("GET", f"/events/{job}") as r:
        body = "".join(r.iter_text())
    return [json.loads(line[5:]) for line in body.splitlines() if line.startswith("data:")]


def test_five_demos_cached_lead_first():
    d = cache.demos()
    assert list(d)[0] == LEAD and len(d) == 5
    for nct, x in d.items():
        assert re.fullmatch(r"[0-9a-f]{64}", x["pdf_sha256"])
        assert cache.demo_by_sha(x["pdf_sha256"])["nct_id"] == nct
        assert x["memo"]["memo"]["headline"] and x["audit"]["risk"]["label"] == "computed, not guessed"


def test_demo_cache_holds_no_later_outcomes():
    for f in (ROOT / "demo_cache").glob("NCT*.json"):
        text = f.read_text()
        for bad in ("status_2020", "why_stopped", "registry_status", "Jan 1, 2020"):
            assert bad not in text, (f.name, bad)


def test_index_shows_disclaimer_tabs_footer(client):
    html = client.get("/").text
    assert DISCLAIMER in html and "no clinical, diagnostic or treatment advice" in html
    assert "Protocol audit" in html and "Validation" in html
    assert "via the CTTI AACT database" in html
    for nct in cache.demos():
        assert nct in html


def test_full_demo_page_renders_every_section(client):
    html = client.get(f"/?tab=audit&demo={LEAD}").text
    for needle in ('id="card"', 'class="badge"', "/page/", 'id="registry-risk"', 'id="sl-sites"',
                   'id="sl-months"', "checkline ok", "Open the Jan 2020 registry record"):
        assert needle in html, needle
    assert "Terminated" not in html  # sealed until opened
    assert cache.demos()[LEAD]["memo"]["memo"]["headline"] in html


def test_saved_replay_streams_all_sections_without_api(client, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no live call in replay")
    monkeypatch.setattr(main, "_live", boom)
    r = client.post("/start", data={"demo": LEAD, "mode": "saved"})
    assert r.status_code == 200 and "Saved result" in r.text
    ev = _events(client, r.text)
    targets = [e["target"] for e in ev]
    assert targets[0] == "card" and targets[-1] == "reveal" and ev[-1]["done"]
    assert {"trace-steps", "trace-summary", "risk", "memo"} <= set(targets)
    assert sum(t == "trace-steps" for t in targets) == len(cache.demos()[LEAD]["audit"]["search"]["steps"])


def test_upload_of_demo_pdf_matches_by_sha(client, monkeypatch):
    d = cache.demos()[LEAD]
    monkeypatch.setattr(cache, "sha256_bytes", lambda b: d["pdf_sha256"])
    r = client.post("/start", data={"mode": "saved"}, files={"pdf": ("p.pdf", b"%PDF-1.4 x", "application/pdf")})
    assert "Saved result" in r.text and LEAD in r.text


def test_non_pdf_and_unknown_upload_with_live_off(client):
    r = client.post("/start", data={"mode": "saved"}, files={"pdf": ("p.pdf", b"hello", "application/pdf")})
    assert "not a PDF" in r.text
    r = client.post("/start", data={"mode": "saved"}, files={"pdf": ("p.pdf", b"%PDF-1.4 new", "application/pdf")})
    assert "Live mode is off" in r.text


def test_live_gates_cap_and_visitor_limit(client, monkeypatch):
    started = []
    monkeypatch.setattr(main, "_live", lambda *a: started.append(a))
    monkeypatch.setattr(main, "_demo_pdf", lambda d: None)
    monkeypatch.setattr(main, "_last_live", {})
    assert "Live mode is off" in client.post("/start", data={"demo": LEAD, "mode": "live"}).text
    monkeypatch.setenv("TRIAL_COPILOT_LIVE", "1")
    monkeypatch.setenv("META_API_KEY", "test-not-a-key")
    r = client.post("/start", data={"demo": LEAD, "mode": "live"})
    assert "Live run on Meta API" in r.text
    assert "One live run per visitor" in client.post("/start", data={"demo": LEAD, "mode": "live"}).text
    monkeypatch.setattr(main, "_last_live", {})
    main._add_spend(main.DAILY_CAP)
    assert "budget" in client.post("/start", data={"demo": LEAD, "mode": "live"}).text
    assert len(started) <= 1


def test_reveal_only_for_demos(client):
    r = client.get(f"/reveal/{LEAD}")
    assert r.status_code == 200 and "Terminated" in r.text and "registry-reported" in r.text
    assert client.get("/reveal/NCT00000001").status_code == 404


def test_validation_tab_has_no_invented_numbers(client):
    """Every number on the tab comes from the saved backtest summaries, none is typed into the template."""
    html = client.get("/?tab=validation").text
    h = json.loads((ROOT / "backtest" / "heldout_summary.json").read_text())
    assert "Not run yet." not in html and "prior research, before the hackathon" in html
    assert f"AUC {h['primary']['B']['auc']['auc']:.2f}" in html and "a tie" in html and "only large gains were detectable" in html
    tpl = (ROOT / "app" / "templates" / "validation.html").read_text()
    for typed in ("0.66", "0.59", "0.73", "13.8", "6.1%", "6.3%"):
        assert typed not in tpl, typed


def test_model_code_never_reads_reveal():
    for name in ("agent.py", "tools.py", "risk.py", "audit.py", "memo.py", "extract.py", "view.py"):
        p = ROOT / "app" / name
        if p.exists():
            t = p.read_text()
            for bad in ("reveal.json", "REVEAL_FILE", "cache.reveal", "demo_cache"):
                assert bad not in t, (name, bad)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_js_slider_maths_matches_python():
    q = [0.05, 0.1, 0.18, 0.32, 0.5, 0.83, 1.4]
    cases = [(112, 20, 56, 0), (112, 5, 36, 0), (112, 1, 3, 0), (400, 40, 24, 6), (60, 10, 12, 18), (112, 200, 60, 0)]
    js = (f"const m=require({json.dumps(str(ROOT / 'app/static/app.js'))});"
          f"const q={json.dumps(q)};const c={json.dumps(cases)};"
          "console.log(JSON.stringify(c.map(([n,s,mo,o])=>m.whatIf(n,s,mo,q,o))));")
    out = json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)
    for (n, s, mo, o), got in zip(cases, out):
        p = risk.pace(n, s, mo)
        assert abs(got["pace"] - p) < 1e-12
        assert got["share"] == risk.share_at_least(q, risk.pace(n, s, mo + o))


def test_slider_defaults_reproduce_saved_share():
    from app import view
    for nct, d in cache.demos().items():
        ctx = view.full_context(d)
        sl, sp = ctx["slider"], ctx["sp"]
        if not sl or sp.get("patients_per_site_per_month") is None or not sl["q"]:
            continue
        got = risk.share_at_least(sl["q"], risk.pace(sl["planned"], sl["sites"], sl["months"] + sl["offset"]))
        assert got == sp["share_of_completed_comparables_at_least_this_fast"], nct


def test_every_demo_memo_passes_the_stricter_check():
    from app import memo
    for nct, d in cache.demos().items():
        m = d["memo"]
        assert m["check"]["passed"], nct
        rr = d["audit"]["registry_risk"]
        need = [memo._pct(rr["risk"]), memo._pct(rr["base_rate_heldout"]["rate"])]
        assert memo.check_headline(m["memo"]["headline"], need)["problems"] == [], nct
        assert m["check"]["claims"] == [], nct


def test_risk_panel_has_no_rate_multipliers_and_labels_post_hoc_parts(client):
    html = client.get(f"/?tab=audit&demo={LEAD}").text
    assert "computed, not guessed" not in html and "× that" not in html and "× the pool" not in html
    assert "Exploratory check, chosen after the held-out outcomes were read" in html
    assert "made the headline number after that test" in html
    assert "completed comparables with enrollment, site and date data" in html and "planned patients ÷" in html
    assert "competing trials were not tested" in html  # memo points heading


def test_validation_tab_states_post_hoc_headline_choice(client):
    html = client.get("/?tab=validation").text
    assert "made the app&#39;s headline number after this result" in html or "made the app's headline number after this result" in html
    assert "table rows are point estimates" in html and "Brier score" in html
