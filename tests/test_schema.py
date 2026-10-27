import jsonschema

from app.card_schema import CARD_FIELDS, card_json_schema
from app.extract import cost_usd, merge_card

TEXT = {"phase": "Phase 2", "planned_enrollment": None,
        "enrollment_per_arm": [{"arm": "A", "n": 20}, {"arm": "B", "n": "20"}],
        "n_arms": 2, "allocation": "Non-Randomised", "masking": "Open Label", "placebo_arm": False,
        "min_age_years": 18, "max_age_years": None, "sponsor_type": "Industry",
        "planned_countries": 10, "planned_sites": "57", "enrollment_period_months": None,
        "required_biomarker": None, "max_prior_lines": "1 prior platinum regimen",
        "washout_days_max": 28, "performance_status_requirement": "ECOG 0-1",
        "brain_mets_allowed": "Treated/stable only", "scheduled_visits_total": 9,
        "visits_first_12_weeks": 6, "mandatory_fresh_biopsy": False,
        "inpatient_stay_required": False, "schedule_of_assessments_pages": [11, 13],
        "protocol_version": "Amendment (a)",
        "_pages": {"phase": 1, "enrollment_per_arm": [30], "n_arms": 1, "allocation": [1],
                   "masking": 1, "placebo_arm": 1, "min_age_years": 20, "sponsor_type": 1,
                   "planned_countries": 999, "planned_sites": 30, "max_prior_lines": 20,
                   "washout_days_max": 21, "performance_status_requirement": 20,
                   "brain_mets_allowed": 21}}
VISION = {"scheduled_visits_total": 10, "visits_first_12_weeks": 7, "visits_open_ended": True,
          "mandatory_fresh_biopsy": False, "inpatient_stay_required": False,
          "schedule_of_assessments_pages": [11, 13], "visit_count_basis": "Columns counted once.",
          "_pages": {"scheduled_visits_total": [11, 13], "visits_first_12_weeks": [13, 40],
                     "visits_open_ended": 13, "mandatory_fresh_biopsy": 13,
                     "inpatient_stay_required": 13, "visit_count_basis": 13}}
SCHEDULE = {"selected": [11, 13], "all_schedule_pages": [11, 13]}


def _result():
    card, pages, src, flags = merge_card(TEXT, VISION, n_pages=74, schedule=SCHEDULE)
    return {"card": card, "_pages": pages, "_field_source": src, "flags": flags,
            "source": {}, "runs": []}


def test_card_passes_schema():
    r = _result()
    jsonschema.validate(r, card_json_schema())
    assert set(r["card"]) == set(CARD_FIELDS)


def test_forbidden_keys_never_reach_the_card():
    r = _result()
    assert "protocol_version" not in r["card"]
    assert any("forbidden" in f for f in r["flags"])


def test_per_arm_sum_and_enum_coercion():
    r = _result()
    assert r["card"]["planned_enrollment"] == 40
    assert r["_field_source"]["planned_enrollment"] == "code"
    assert r["card"]["allocation"] == "Non-Randomized"
    assert r["card"]["masking"] == "None (Open Label)"
    assert r["card"]["planned_sites"] == 57


def test_vision_fields_win_and_bad_pages_are_dropped():
    r = _result()
    assert r["card"]["scheduled_visits_total"] == 10
    assert r["_field_source"]["scheduled_visits_total"] == "vision"
    assert "planned_countries" not in r["_pages"]          # page 999 is out of range
    assert r["_pages"]["visits_first_12_weeks"] == [13]    # page 40 was not an image
    assert r["_pages"]["phase"] == [1]


def test_cost():
    u = {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000,
         "prompt_tokens_details": {"cached_tokens": 0}}
    assert abs(cost_usd(u) - 5.50) < 1e-9
