from app.visits import count_visits, contact_type

# Myeloma demo NCT02720510 (Table 7-1): 21-day induction cycles, then 84-day maintenance.
MYELOMA = {
    "screening_visits": [{"label": "Screening Day -21 to 1", "contact": "clinic"}],
    "periods": [
        {"label": "Cycle 1", "cycle_length_days": 21, "first_cycle": 1, "n_cycles": 1,
         "visits": [{"day": d, "contact": "clinic"} for d in (1, 4, 8, 11)]},
        {"label": "Cycles 2-5", "cycle_length_days": 21, "first_cycle": 2, "n_cycles": 4,
         "visits": [{"day": d, "contact": "clinic"} for d in (1, 4, 8, 11)]
         + [{"day": 21, "contact": "clinic", "only_in_cycles": [4]}]},
        {"label": "Cycle 6", "cycle_length_days": 84, "first_cycle": 6, "n_cycles": 1,
         "visits": [{"day": d, "contact": "clinic"} for d in (1, 29, 57)]},
        {"label": "Cycle 7+", "cycle_length_days": 84, "first_cycle": 7, "n_cycles": None,
         "repeats_until_stop": True, "visits": [{"day": 1, "contact": "clinic"}]},
        {"label": "End of treatment", "visits": [{"day": None, "conditional": True}]},
    ],
}


def test_myeloma_open_ended_cycles():
    c = count_visits(MYELOMA)
    assert c["clinic_visits_first_26_weeks"] == 24   # C1 4 + C2-5 17 + C6 3; C7 starts day 190
    assert c["clinic_visits_first_12_weeks"] == 18   # through day 85 (cycle 5 day 1)
    assert c["remote_visits_first_26_weeks"] == 0
    assert c["screening_clinic_visits"] == 1
    assert c["visits_open_ended"] is True


def test_week_timeline_with_phone_visits():
    # COPD style: visits every 4 weeks, phone calls in between.
    visits = [{"label": f"V{i}", "week": w, "contact": "phone" if i % 2 else "clinic"}
              for i, w in enumerate(range(0, 53, 2), start=2)]
    sched = {"screening_visits": [{"label": "V1", "contact": "clinic"}],
             "periods": [{"label": "Treatment", "day_reference": "study_day", "visits": visits}]}
    c = count_visits(sched)
    # weeks 0..26 -> days 1..183: 14 visit days, alternating clinic/phone starting with clinic
    assert c["clinic_visits_first_26_weeks"] == 7
    assert c["remote_visits_first_26_weeks"] == 7
    assert c["visits_open_ended"] is False


def test_same_day_contacts_count_once_and_clinic_wins():
    sched = {"periods": [{"visits": [{"day": 1, "contact": "phone"}, {"day": 1, "contact": "clinic"},
                                     {"day": 15, "contact": "telephone contact"}]}]}
    c = count_visits(sched)
    assert c["clinic_visits_first_26_weeks"] == 1 and c["remote_visits_first_26_weeks"] == 1


def test_follow_up_after_fixed_treatment():
    sched = {"periods": [
        {"label": "Cycles 1-4", "cycle_length_days": 21, "first_cycle": 1, "n_cycles": 4,
         "visits": [{"day": 1, "contact": "clinic"}]},
        {"label": "Follow-up", "day_reference": "period_start", "repeat_every_days": 42,
         "repeats_until_stop": True, "visits": []},
    ]}
    c = count_visits(sched)
    # treatment days 1, 22, 43, 64; follow-up from day 85: days 126, 168
    assert c["clinic_visits_first_26_weeks"] == 6
    assert c["visits_open_ended"] is False   # fixed 4 cycles; only follow-up runs on


def test_no_schedule():
    c = count_visits(None)
    assert c["clinic_visits_first_26_weeks"] is None and c["visit_count_basis"] is None


def test_contact_synonyms():
    assert contact_type("Telephone call") == "phone"
    assert contact_type("Home nurse visit") == "home"
    assert contact_type(None) == "clinic"


def test_repeat_without_end_is_counted_once_not_open_ended():
    sched = {"periods": [{"visits": [{"day": 1}, {"day": 29}]},
                         {"label": "Phone FU", "repeat_every_days": 28, "contact": "phone", "visits": []}]}
    c = count_visits(sched)
    assert c["clinic_visits_first_26_weeks"] == 2 and c["remote_visits_first_26_weeks"] == 1
    assert c["visits_open_ended"] is False


# --- Oct 27 (second round): surgery, invasive procedures, sensitivity count -------------

def _surgery_schedule(surgery_conditional=False):
    return {"screening_visits": [{"label": "Screening", "contact": "clinic"},
                                 {"label": "Run-in call", "contact": "phone"}],
            "periods": [
                {"label": "Pre-op treatment", "day_reference": "study_day",
                 "visits": [{"label": "D1", "day": 1}, {"label": "D29", "day": 29}, {"label": "D57", "day": 57}]},
                {"label": "Surgery", "day_reference": "study_day",
                 "visits": [{"label": "Pre-op assessment", "day": 85},
                            {"label": "Surgery", "day": 92, "day_estimated": True,
                             "kind": "major_procedure", "inpatient_days": 5,
                             "conditional": surgery_conditional},
                            {"label": "Post-op visit", "day": 106}]},
                {"label": "Follow-up", "day_reference": "period_start", "repeat_every_days": 91,
                 "repeats_until_stop": True, "visits": []}]}


def test_surgery_is_a_major_procedure_not_a_visit():
    r = count_visits(_surgery_schedule())
    days = [d for d, _ in r["visit_days_first_26_weeks"]]
    assert 92 not in days
    assert days == [1, 29, 57, 85, 106]
    assert r["clinic_visits_first_26_weeks"] == 5
    assert r["major_procedure_required"] is True
    assert r["major_procedure_day"] == 92
    assert r["major_procedure_inpatient_days"] == 5


def test_conditional_surgery_still_anchors_timeline_but_is_not_required():
    r = count_visits(_surgery_schedule(surgery_conditional=True))
    assert r["clinic_visits_first_26_weeks"] == 5
    assert r["major_procedure_required"] is False


def test_surgery_label_caught_without_kind():
    s = _surgery_schedule()
    s["periods"][1]["visits"][1].pop("kind")
    r = count_visits(s)
    assert r["clinic_visits_first_26_weeks"] == 5
    assert r["major_procedure_required"] is True


def test_post_surgery_visit_label_still_counts():
    from app.visits import is_major_procedure
    assert is_major_procedure({"label": "Surgical resection"})
    assert not is_major_procedure({"label": "Post-surgery follow-up"})
    assert not is_major_procedure({"label": "Pre-operative assessment"})


def test_sensitivity_count_includes_screening_and_phone():
    r = count_visits(_surgery_schedule())
    # screening clinic + run-in phone + days 1, 29, 57, 85 (all within day 85)
    assert r["contacts_screening_to_week_12"] == 6
    assert r["clinic_visits_first_12_weeks"] == 4


def _myeloma_like():
    return {"screening_visits": [{"label": "Screening", "contact": "clinic"}],
            "periods": [{"label": "Cycles 1-8", "cycle_length_days": 21, "first_cycle": 1, "n_cycles": 8,
                         "visits": [{"label": "D1", "day": 1}, {"label": "D8", "day": 8}]}]}


def test_bone_marrow_standard_of_care_is_not_a_research_biopsy():
    procs = [{"name": "Bone marrow aspirate/biopsy", "purpose": "standard_of_care", "mandatory": True,
              "occurrences": [{"screening": True}, {"cycle": 4, "day": 21}]},
             {"name": "Bone marrow to confirm CR", "purpose": "standard_of_care", "mandatory": False,
              "occurrences": [{"cycle": 8, "day": 1}]}]
    r = count_visits(_myeloma_like(), procs)
    assert r["mandatory_fresh_biopsy"] is False
    assert r["soc_invasive_procedures_first_26_weeks"] == 2
    assert r["research_invasive_procedures_first_26_weeks"] == 0


def test_research_biopsy_counted_with_repeats_inside_window():
    procs = [{"name": "Tumour biopsy (PD)", "purpose": "research_only", "mandatory": True,
              "occurrences": [{"screening": True}, {"cycle": 2, "day": 1}], "then_every_days": 63}]
    r = count_visits(_myeloma_like(), procs)
    # screening, C2D1 = day 22, then 85, 148 (211 is past day 183)
    assert r["research_invasive_procedures_first_26_weeks"] == 4
    assert r["mandatory_fresh_biopsy"] is True


def test_no_procedure_list_gives_nulls():
    r = count_visits(_myeloma_like())
    assert r["mandatory_fresh_biopsy"] is None
    assert r["soc_invasive_procedures_first_26_weeks"] is None


def test_surgery_label_with_timing_words_is_still_surgery():
    from app.visits import is_major_procedure
    assert is_major_procedure({"label": "Surgery (4-6 weeks after the Day 57 scan)"})
    assert not is_major_procedure({"label": "Post-op visit"})


def test_day_zero_inside_a_period_is_day_one():
    s = {"screening_visits": [{"label": "V1", "contact": "clinic"}],
         "periods": [{"label": "Treatment", "day_reference": "study_day",
                      "visits": [{"label": "V2 w0", "day": 0}, {"label": "V3 w4", "week": 4}]}]}
    r = count_visits(s)
    assert r["screening_clinic_visits"] == 1
    assert [d for d, _ in r["visit_days_first_26_weeks"]] == [1, 29]


# ---- Day 2 fixes -------------------------------------------------------------------------
from app.visits import procedure_is_mandated, screening_window_from_visits  # noqa: E402


def test_highly_recommended_is_not_mandated():
    egfr = {"name": "Mediastinoscopy / EUS / EBUS", "purpose": "standard_of_care", "mandatory": True,
            "requirement_wording": "highly recommended", "occurrences": [{"screening": True}]}
    assert procedure_is_mandated(egfr) is False
    for w in ("optional", "if clinically indicated", "strongly encouraged", "at the investigator's discretion",
              "recommended", "if available"):
        assert procedure_is_mandated(dict(egfr, requirement_wording=w)) is False, w
    for w in ("must undergo", "required", "X in schedule", None):
        assert procedure_is_mandated(dict(egfr, requirement_wording=w)) is True, w
    assert procedure_is_mandated(dict(egfr, mandatory=False, requirement_wording="required")) is False
    res = count_visits({"screening_visits": [{"label": "Screening"}], "periods": []}, [egfr])
    assert res["soc_invasive_procedures_first_26_weeks"] == 0


def test_screening_window_from_visit_timing():
    copd = [{"label": "V1 (w-4)", "contact": "clinic"}, {"label": "V2 (w -3)", "contact": "clinic"},
            {"label": "V3 (w -1)", "contact": "clinic"}]
    assert screening_window_from_visits(copd) == 28
    assert screening_window_from_visits([{"label": "Screening", "week": -4}]) == 28
    assert screening_window_from_visits([{"label": "Screening Day -28 to -1"}]) == 28
    assert screening_window_from_visits([{"label": "Screening", "day": -21}]) == 21
    assert screening_window_from_visits([{"label": "Screening"}]) is None
    assert screening_window_from_visits(None) is None
