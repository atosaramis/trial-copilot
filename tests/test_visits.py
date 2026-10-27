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
