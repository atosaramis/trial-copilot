"""Trial card fields and the JSON schema the final card must pass.

The card is small on purpose (build spec section 4). Protocol version, dates and
amendment details are never part of it: they can leak how the trial went.
"""
from __future__ import annotations

ENUMS = {
    "phase": ["Phase 1", "Phase 1/2", "Phase 2", "Phase 2/3", "Phase 3", "Phase 4"],
    "allocation": ["Randomized", "Non-Randomized", "Single group"],
    "masking": ["None (Open Label)", "Single", "Double", "Triple", "Quadruple"],
    "sponsor_type": ["Industry", "Academic/Other", "NIH", "Cooperative group"],
    "brain_mets_allowed": ["Yes", "No", "Treated/stable only", "Required", "Not applicable"],
}

# Visit and procedure counts are made by code from the transcribed schedule (app/visits.py),
# never by the model.
CODE_VISIT_FIELDS = ["clinic_visits_first_26_weeks", "remote_visits_first_26_weeks",
                     "clinic_visits_first_12_weeks", "remote_visits_first_12_weeks",
                     "screening_clinic_visits", "visits_open_ended",
                     "contacts_screening_to_week_12",
                     "major_procedure_required", "major_procedure_day", "major_procedure_inpatient_days",
                     "soc_invasive_procedures_first_26_weeks", "research_invasive_procedures_first_26_weeks",
                     "mandatory_fresh_biopsy", "visit_count_basis"]

INT_FIELDS = ["planned_enrollment", "n_arms", "planned_countries", "planned_sites",
              "washout_days_max", "clinic_visits_first_26_weeks", "remote_visits_first_26_weeks",
              "clinic_visits_first_12_weeks", "remote_visits_first_12_weeks", "screening_clinic_visits",
              "contacts_screening_to_week_12", "screening_window_days", "major_procedure_day",
              "major_procedure_inpatient_days", "soc_invasive_procedures_first_26_weeks",
              "research_invasive_procedures_first_26_weeks"]
NUM_FIELDS = ["min_age_years", "max_age_years", "enrollment_period_months"]
BOOL_FIELDS = ["placebo_arm", "mandatory_fresh_biopsy", "inpatient_stay_required", "visits_open_ended",
               "major_procedure_required"]
STR_FIELDS = ["condition", "interventions", "required_biomarker", "max_prior_lines", "performance_status_requirement", "visit_count_basis",
              "age_criterion"]

# Fields read from the visit-schedule page images (vision call).
VISION_FIELDS = ["visit_schedule", "screening_window_days", "invasive_procedures",
                 "inpatient_stay_required", "schedule_of_assessments_pages"]

# Fields read from the full protocol text (text call).
TEXT_FIELDS = ["condition", "interventions", "phase", "planned_enrollment", "enrollment_per_arm", "n_arms", "allocation",
               "masking", "placebo_arm", "min_age_years", "max_age_years", "age_criterion", "sponsor_type",
               "planned_countries", "planned_sites", "enrollment_period_months",
               "required_biomarker", "max_prior_lines", "washout_days_max",
               "performance_status_requirement", "brain_mets_allowed"]

CARD_FIELDS = TEXT_FIELDS + VISION_FIELDS + CODE_VISIT_FIELDS

# Never extracted, never scored. Any key that looks like these is dropped.
FORBIDDEN_KEY_WORDS = ("version", "amendment", "protocol_date", "revision", "edition")


def _nullable(t):
    return {"type": [t, "null"]}


def card_json_schema() -> dict:
    props: dict = {}
    for k, vals in ENUMS.items():
        props[k] = {"enum": vals + [None]}
    for k in INT_FIELDS:
        props[k] = _nullable("integer")
    for k in NUM_FIELDS:
        props[k] = _nullable("number")
    for k in BOOL_FIELDS:
        props[k] = _nullable("boolean")
    for k in STR_FIELDS:
        props[k] = _nullable("string")
    props["enrollment_per_arm"] = {
        "type": "array",
        "items": {"type": "object", "required": ["n"],
                  "properties": {"arm": _nullable("string"), "n": {"type": "integer"}}},
    }
    props["visit_schedule"] = {"type": ["object", "null"]}
    props["invasive_procedures"] = {"type": ["array", "null"], "items": {
        "type": "object", "required": ["name", "purpose", "mandatory"],
        "properties": {"name": {"type": "string"},
                       "purpose": {"enum": ["standard_of_care", "research_only"]},
                       "mandatory": {"type": "boolean"}}}}
    props["schedule_of_assessments_pages"] = {"type": "array", "items": {"type": "integer", "minimum": 1}}
    return {
        "type": "object",
        "required": ["card", "_pages", "_field_source", "source", "runs"],
        "properties": {
            "card": {"type": "object", "required": CARD_FIELDS, "properties": props,
                     "additionalProperties": False},
            "_pages": {"type": "object", "additionalProperties": {
                "type": "array", "items": {"type": "integer", "minimum": 1}}},
            "_field_source": {"type": "object", "additionalProperties": {
                "enum": ["text", "vision", "code", "none"]}},
            "source": {"type": "object"},
            "runs": {"type": "array"},
        },
    }
