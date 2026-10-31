"""Code checks on design numbers (app/design_checks.py) and the finder/grade handling of a protocol
that states different planned totals. Sentences are modelled on real tuning-set protocols."""
from app import design_checks as dc
from app.card_schema import CARD_FIELDS
from app.extract import merge_card
from app.mismatch import finder as f
from app.mismatch.autograde import Snapshot, grade

FILL = "The study drug is given once daily at the clinic visit with food and water. " * 4


def check(card, text_out=None, pages=None):
    card = {k: None for k in CARD_FIELDS} | card
    cites, source, flags = {}, {}, []
    dc.apply(card, cites, source, flags, text_out or {}, [FILL + p for p in pages] if pages else None)
    return card, cites, source, flags


# ---- enrollment: synopsis and body disagree (R26 pattern) ----
SYNOPSIS = "DESIGN Open label, dose escalation, phase 2 clinical trial of kisspeptin in 102 women undergoing IVF."
BODY = "Number and type of patients recruited: 90 women undergoing IVF treatment for infertility."


def test_conflicting_totals_are_both_kept_and_none_is_picked():
    totals = [{"n": 102, "where": "synopsis", "page": 1}, {"n": 90, "where": "study design", "page": 2}]
    card, cites, source, flags = check({"planned_enrollment": 90}, {"planned_enrollment_totals_stated": totals},
                                       [SYNOPSIS, BODY])
    assert card["planned_enrollment"] is None and card["planned_enrollment_values"] == [90, 102]
    assert source["planned_enrollment"] == "code" and cites["planned_enrollment_values"] == [1, 2]
    assert any("internal protocol inconsistency" in x for x in flags)


def test_same_total_twice_is_not_a_conflict():
    totals = [{"n": 90, "where": "synopsis", "page": 2}, {"n": 90, "where": "sample size", "page": 2}]
    card, *_ = check({"planned_enrollment": 90}, {"planned_enrollment_totals_stated": totals}, [SYNOPSIS, BODY])
    assert card["planned_enrollment"] == 90 and card["planned_enrollment_values"] == []


def test_a_stated_total_not_on_its_cited_page_is_dropped():
    totals = [{"n": 102, "where": "synopsis", "page": 1}, {"n": 120, "where": "made up", "page": 2}]
    card, *_ = check({"planned_enrollment": 102}, {"planned_enrollment_totals_stated": totals}, [SYNOPSIS, BODY])
    assert card["planned_enrollment"] == 102 and card["planned_enrollment_values"] == []


def test_total_seen_only_as_a_completer_count_is_flagged():
    _, _, _, flags = check({"planned_enrollment": 30},
                           pages=["Up to 40 subjects will begin the protocol so that 30 subjects complete the study."])
    assert any("completed/evaluable" in x for x in flags)


# ---- arms: single-arm study read as two arms (R42 pattern) is flagged, not overridden ----
# (the prompt folds dose cohorts; parallel population cohorts are separate registry groups)
def test_single_arm_study_read_as_two_arms_is_flagged_not_changed():
    card, cites, source, flags = check({"n_arms": 2, "allocation": "Non-Randomized"}, pages=[
        "This is a Phase II, open-label, non-randomized, multi-center, single arm study of ferric carboxymaltose.",
        "Cohort 2 will initiate enrollment only after all subjects in Cohort 1 have completed 4 weeks of therapy."])
    assert card["n_arms"] == 2 and source.get("n_arms") != "code"
    assert any("single-arm (p.1)" in f for f in flags)


def test_single_arm_mentioned_for_a_prior_study_does_not_change_arms():
    card, _, _, flags = check({"n_arms": 2, "allocation": "Randomized"}, pages=[
        "A previous single-arm study (Smith et al, 2012; 4:1) showed benefit.",
        "Patients will be randomized 1:1 to drug or placebo."])
    assert card["n_arms"] == 2 and not any(f.startswith("n_arms") for f in flags)


def test_randomized_sentence_mentioning_single_arm_is_not_a_single_arm_design():
    card, _, _, flags = check({"n_arms": 2, "allocation": "Randomized"},
                     pages=["Unlike a single-arm design, patients will be randomized to two arms."])
    assert card["n_arms"] == 2 and not any(f.startswith("n_arms") for f in flags)


# ---- sites: planning assumption only (R30 pattern) ----
ASSUME = "10.8 Estimated accrual Estimates of accrual for purposes of statistical planning assume 40 enrollment sites averaging 5 subjects per year over a 4 year enrollment period."


def test_site_count_seen_only_in_a_planning_assumption_is_dropped():
    card, cites, source, flags = check({"planned_sites": 40}, pages=[ASSUME])
    assert card["planned_sites"] is None and source["planned_sites"] == "code"
    assert any("planning/statistical assumption" in x for x in flags)


def test_site_count_also_stated_as_a_plan_is_kept():
    card, *_ = check({"planned_sites": 40}, pages=[ASSUME, "The trial will be conducted at approximately 40 sites."])
    assert card["planned_sites"] == 40


def test_myeloma_demo_site_plan_is_kept():
    card, *_ = check({"planned_sites": 20},
                     pages=["The study will be conducted at approximately 20 centers in the United States."])
    assert card["planned_sites"] == 20


def test_scan_without_text_only_uses_the_model_totals():
    totals = [{"n": 102, "page": 1}, {"n": 90, "page": 2}]
    card, *_ = check({"planned_enrollment": 90}, {"planned_enrollment_totals_stated": totals}, None)
    assert card["planned_enrollment_values"] == [90, 102]


# ---- finder and grade ----
REG = {"phase": "Phase 2", "allocation": "Non-Randomized", "n_arms": 1, "enrollment": 102,
       "enrollment_type": "Anticipated", "n_sites_2017": 1, "n_countries": 1}


def test_finder_reports_an_inconsistent_protocol_as_one_low_doubtful_row():
    card = {"phase": "Phase 2", "allocation": "Non-Randomized", "n_arms": 1, "planned_enrollment": None,
            "planned_enrollment_values": [90, 102]}
    res = f.find_mismatches("NCT00000002", card, REG, [FILL + SYNOPSIS, FILL + BODY])
    (m,) = [x for x in res.mismatches if x.field == "enrollment"]
    assert m.protocol_value == "90 / 102" and m.severity == "low" and m.traps == ("protocol_inconsistent",)
    assert m.doubtful_reading and "registry matches 102" in m.note and m.evidence.page == 2
    g = grade(m, [Snapshot("2020-01-01", enrollment=102, enrollment_type="Anticipated")])
    assert g.category == "ambiguous" and "different planned totals" in g.reason


def test_v2_ignores_the_values_list():
    card = {"planned_enrollment": None, "planned_enrollment_values": [90, 102]}
    res = f.find_mismatches("NCT00000002", card, REG, None, rules="v2")
    assert "enrollment" not in res.compared


def test_merge_then_checks_keep_schema_shape():
    from tests.test_schema import TEXT, VISION, SCHEDULE
    card, pages, src, flags = merge_card(TEXT, VISION, n_pages=74, schedule=SCHEDULE)
    dc.apply(card, pages, src, flags, TEXT, None)
    assert card["planned_enrollment_values"] == []
