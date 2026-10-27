import math

import pytest

from app.risk import (achieved_paces, assess, months_between, pace, quantiles, share_at_least, what_if,
                      wilson)


def test_wilson_known_values():
    lo, hi = wilson(4, 40)
    assert lo == pytest.approx(0.0396, abs=1e-3) and hi == pytest.approx(0.2313, abs=1e-3)
    assert wilson(0, 10)[0] == 0.0
    assert wilson(10, 10)[1] == pytest.approx(1.0)
    assert wilson(0, 0) == (None, None)
    with pytest.raises(ValueError):
        wilson(5, 3)


def test_pace_and_months():
    assert pace(112, 5, 20) == pytest.approx(1.12)
    assert pace(112, 0, 20) is None and pace(None, 5, 20) is None
    assert months_between("2016-06-01", "2021-02-01") == pytest.approx(56.0, abs=0.1)
    assert months_between("2016-06-01", "2015-01-01") is None


def test_quantiles_and_share():
    vals = sorted(float(x) for x in range(1, 101))
    q = quantiles(vals)
    assert len(q) == 101 and q[0] == 1 and q[-1] == 100 and q[50] == pytest.approx(50.5)
    assert share_at_least(q, 0.5) == 1.0
    assert share_at_least(q, 1000) == 0.0
    assert share_at_least(q, 50.5) == pytest.approx(0.5, abs=0.01)
    assert share_at_least([], 3) is None


def test_achieved_paces_use_completed_only():
    rows = [{"outcome_2017": "completed", "enrollment": 120, "n_sites_2017": 10,
             "start_date": "2010-01-01", "primary_completion_date": "2011-01-01"},
            {"outcome_2017": "terminated_poor_enrollment", "enrollment": 3, "n_sites_2017": 10,
             "start_date": "2010-01-01", "primary_completion_date": "2011-01-01"}]
    p = achieved_paces(rows)
    assert len(p) == 1 and p[0] == pytest.approx(120 / (10 * 365 / 30.44))


def test_what_if_moves_with_sliders():
    q = quantiles(sorted([0.1, 0.2, 0.3, 0.5, 1.0]))
    base = what_if(112, 5, 20, q)
    more_sites = what_if(112, 20, 20, q)
    assert base["patients_per_site_per_month"] == pytest.approx(1.12)
    assert more_sites["patients_per_site_per_month"] == pytest.approx(0.28)
    assert more_sites["share_of_completed_comparables_at_least_this_fast"] > \
        base["share_of_completed_comparables_at_least_this_fast"]


def test_assess_protocol_first_registry_fallback(pools):
    from app.tools import RegistryTools
    t = RegistryTools(pools, exclude_nct="NCT02720510", target_enrollment=112)
    s = t.search_comparable_trials(["myeloma"], ["Phase 2"])
    c = t.count_competing_trials(["myeloma"])
    reg = t.registry_2017("NCT02720510")
    card = {"planned_enrollment": 112, "planned_sites": 20, "enrollment_period_months": None}
    r = assess(card, reg, t.results[s["result_id"]], t.results[c["result_id"]], t.pool_totals())
    assert r["label"] == "computed, not guessed"
    assert r["comparable_trials"]["events"] == 4 and r["comparable_trials"]["n"] == 40
    assert r["all_trials_in_pool"]["events"] == 5 and r["all_trials_in_pool"]["n"] == 60
    sp = r["site_pace"]
    assert sp["sites"] == 20 and sp["sites_source"] == "protocol" and sp["registry_sites_2017"] == 5
    assert sp["months_source"].startswith("registry_2017")
    assert sp["patients_per_site_per_month"] == pytest.approx(112 / (20 * 56.0), rel=0.01)
    assert r["competing_trials"]["n_recruiting_jan_2017"] == 5
    assert any("protocol says 20" in f for f in r["flags"])
    assert len(r["slider_model"]["pace_quantiles"]) == 101
    # No sites in the protocol: the Jan 2017 registry count is the fallback.
    r2 = assess({"planned_enrollment": 112}, reg, t.results[s["result_id"]], None, t.pool_totals())
    assert r2["site_pace"]["sites"] == 5 and r2["site_pace"]["sites_source"] == "registry_2017"
    assert r2["competing_trials"] is None
    assert not math.isnan(r2["site_pace"]["patients_per_site_per_month"])


def test_assess_upload_without_registry():
    r = assess({"planned_enrollment": 100, "planned_sites": 10, "enrollment_period_months": 20},
               None, None, None, {"n": 100, "events": 4})
    assert r["site_pace"]["patients_per_site_per_month"] == pytest.approx(0.5)
    assert r["comparable_trials"] is None and r["relative_to_pool"] is None
