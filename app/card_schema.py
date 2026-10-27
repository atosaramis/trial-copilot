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

INT_FIELDS = ["planned_enrollment", "n_arms", "planned_countries", "planned_sites",
              "washout_days_max", "scheduled_visits_total", "visits_first_12_weeks"]
NUM_FIELDS = ["min_age_years", "max_age_years", "enrollment_period_months"]
BOOL_FIELDS = ["placebo_arm", "mandatory_fresh_biopsy", "inpatient_stay_required", "visits_open_ended"]
STR_FIELDS = ["required_biomarker", "max_prior_lines", "performance_status_requirement", "visit_count_basis"]

# Fields read from the visit-schedule page images (vision call).
VISION_FIELDS = ["scheduled_visits_total", "visits_first_12_weeks", "visits_open_ended",
                 "mandatory_fresh_biopsy", "inpatient_stay_required",
                 "schedule_of_assessments_pages", "visit_count_basis"]

# Fields read from the full protocol text (text call).
TEXT_FIELDS = ["phase", "planned_enrollment", "enrollment_per_arm", "n_arms", "allocation",
               "masking", "placebo_arm", "min_age_years", "max_age_years", "sponsor_type",
               "planned_countries", "planned_sites", "enrollment_period_months",
               "required_biomarker", "max_prior_lines", "washout_days_max",
               "performance_status_requirement", "brain_mets_allowed"]

CARD_FIELDS = TEXT_FIELDS + VISION_FIELDS

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
