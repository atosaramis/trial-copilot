"""The headline number: the locked registry baseline recalibrated with the frozen rule."""
import json
import math
from pathlib import Path

from app import registry_risk as rr

ROOT = Path(__file__).resolve().parents[1]


def test_recalibration_matches_the_frozen_addendum():
    r = rr.MODEL["recalibration"]
    assert (round(r["a"], 6), round(r["b"], 6)) == (0.797195, 1.053194)
    assert r["addendum_sha256"].startswith("efa4ad81") and r["addendum_sha256"].endswith("0dc4")
    assert "p_B = 1 / (1 + exp(-(0.797195 + 1.053194 * logit(p_A))))" in (ROOT / "docs" / "preregistration-addendum.md").read_text()


def test_heldout_reference_adds_up_and_matches_the_summary():
    ref = rr.MODEL["heldout_reference"]
    h = json.loads((ROOT / "backtest" / "heldout_summary.json").read_text())
    assert sum(b["n"] for b in ref["bins"]) == h["n"] == 873
    assert sum(b["events"] for b in ref["bins"]) == h["events"] == 53
    assert ref["auc"]["auc"] == h["primary"]["B"]["auc"]["auc"]
    assert ref["bins"][0]["min"] == 0.0 and ref["bins"][-1]["max"] == 1.0


def test_us_site_follows_the_locked_first_eight_countries_rule():
    eleven = "Canada, Germany, United Kingdom, Italy, Israel, Mexico, Spain, Russian Federation, Argentina, United States, Sweden"
    assert rr._us_in_first8(eleven) == 0.0          # US is 10th alphabetically, as in the locked baseline
    assert rr._us_in_first8("United States, Canada") == 1.0
    assert rr._us_in_first8("Korea, Republic of, United States") == 1.0


def test_assess_is_monotone_and_carries_context():
    base = {"phase": "Phase 2", "enrollment": 100, "n_sites_2017": 10, "n_countries": 1, "countries": "United States",
            "lead_class": "Industry", "start_date": "2016-06-01", "primary_completion_date": "2018-06-01",
            "criteria": "Inclusion:\n- a\n- b", "conditions": "Multiple Myeloma"}
    a = rr.assess(base)
    assert 0 < a["risk"] < 1 and a["inputs"].startswith("Jan 5, 2017 registry record")
    lo, hi = a["same_fifth_heldout"]["range"]
    assert lo <= a["risk"] <= hi and a["base_rate_heldout"]["rate"] == 0.0607
    bigger = rr.assess({**base, "enrollment": 1000, "n_sites_2017": 100})
    assert bigger["risk"] != a["risk"]
    assert rr.assess(None) is None


def test_wilson_interval():
    lo, hi = rr.wilson(15, 174)
    assert math.isclose(lo, 0.0529, abs_tol=1e-3) and math.isclose(hi, 0.1374, abs_tol=1e-3)
