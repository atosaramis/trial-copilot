import jsonschema

from app.card_schema import CARD_FIELDS, card_json_schema
from app.extract import cost_usd, merge_card

TEXT = {"phase": "Phase 2", "planned_enrollment": None,
        "enrollment_per_arm": [{"arm": "A", "n": 20}, {"arm": "B", "n": "20"}],
        "n_arms": 2, "allocation": "Non-Randomised", "masking": "Open Label", "placebo_arm": False,
        "min_age_years": 19, "max_age_years": None, "sponsor_type": "Industry",
        "planned_countries": 10, "planned_sites": "57", "enrollment_period_months": None,
        "required_biomarker": None, "max_prior_lines": "1 prior platinum regimen",
        "washout_days_max": 28, "performance_status_requirement": "ECOG 0-1",
        "brain_mets_allowed": "Treated/stable only", "age_criterion": "Age > 18 years",
        "mandatory_fresh_biopsy": False,
        "inpatient_stay_required": False, "schedule_of_assessments_pages": [11, 13],
        "protocol_version": "Amendment (a)",
        "_pages": {"phase": 1, "enrollment_per_arm": [30], "n_arms": 1, "allocation": [1],
                   "masking": 1, "placebo_arm": 1, "min_age_years": 20, "age_criterion": 20, "sponsor_type": 1,
                   "planned_countries": 999, "planned_sites": 30, "max_prior_lines": 20,
                   "washout_days_max": 21, "performance_status_requirement": 20,
                   "brain_mets_allowed": 21}}
VISION = {"screening_visits": [{"label": "Screening", "contact": "clinic"}],
          "periods": [{"label": "Treatment", "cycle_length_days": 21, "first_cycle": 1, "n_cycles": None,
                       "repeats_until_stop": True,
                       "visits": [{"label": "D1", "day": 1, "contact": "clinic"},
                                  {"label": "D8", "day": 8, "contact": "phone"}]}],
          "mandatory_fresh_biopsy": False, "inpatient_stay_required": None,
          "schedule_of_assessments_pages": [11, 13], "schedule_notes": "",
          "_pages": {"periods": [11, 13, 40], "mandatory_fresh_biopsy": 13}}
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


def test_visit_counts_come_from_code_and_bad_pages_are_dropped():
    r = _result()
    c = r["card"]
    # 21-day cycles until progression: Day 1 clinic (days 1, 22, ... 169) and Day 8 phone.
    assert c["clinic_visits_first_26_weeks"] == 9
    assert c["remote_visits_first_26_weeks"] == 9      # days 8, 29, ... 176
    assert c["clinic_visits_first_12_weeks"] == 5      # days 1, 22, 43, 64, 85
    assert c["screening_clinic_visits"] == 1
    assert c["visits_open_ended"] is True
    assert r["_field_source"]["clinic_visits_first_26_weeks"] == "code"
    assert r["_pages"]["clinic_visits_first_26_weeks"] == [11, 13]   # page 40 was not sent
    assert "planned_countries" not in r["_pages"]          # page 999 is out of range
    assert r["_pages"]["phase"] == [1]
    # inpatient stay was null on the schedule pages, so the text reading is used
    assert r["_field_source"]["inpatient_stay_required"] == "text"


def test_yes_from_either_reading_wins():
    text = dict(TEXT, inpatient_stay_required=True, _pages=dict(TEXT["_pages"], inpatient_stay_required=30))
    vision = dict(VISION, inpatient_stay_required=False)
    card, pages, src, flags = merge_card(text, vision, n_pages=74, schedule=SCHEDULE)
    assert card["inpatient_stay_required"] is True and src["inpatient_stay_required"] == "code"
    assert pages["inpatient_stay_required"] == [30]


def test_age_rule_applied_by_code():
    r = _result()
    assert r["card"]["min_age_years"] == 18     # "Age > 18 years" -> 18 (registry convention)
    assert r["_field_source"]["min_age_years"] == "code"
    assert any("min_age_years: model read 19" in f for f in r["flags"])


def test_cost():
    u = {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000,
         "prompt_tokens_details": {"cached_tokens": 0}}
    assert abs(cost_usd(u) - 5.50) < 1e-9
