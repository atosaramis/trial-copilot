"""v3 finder rules: patterns the investigation agent found among its extraction-error verdicts.
Each case is modelled on a real tuning-set protocol sentence; v2 must keep its old answer."""
from app.mismatch import finder as f
from tests.test_mismatch_finder import by_field, pages, run


def both(card, reg, text, field):
    pg = pages(text)
    return by_field(run(card, reg, pg, rules="v2"), field), run(card, reg, pg, rules="v3")


def test_up_to_n_sites_is_a_doubtful_maximum_not_a_clear():
    # "up to 65 sites" against 9 registered is often a lagging registry, so it stays visible
    old, new = both({"planned_sites": 5}, {"n_sites_2017": 2},
                    "The study is intended to be conducted in up to 5 centers within the U.S.A.", "sites")
    assert old[0].traps == ()
    (m,) = by_field(new, "sites")
    assert m.evidence.kind == "upper_bound" and "upper_bound" in m.traps and m.doubtful_reading
    assert m.severity == "medium"                  # high capped to medium for a doubtful reading


def test_minimum_of_n_and_n_or_more_are_minimums():
    _, new = both({"planned_sites": 3}, {"n_sites_2017": 12},
                  "The study is conducted at a minimum of three study centres which will screen patients.", "sites")
    assert by_field(new, "sites") == [] and new.cleared[0].traps == ("lower_bound",)
    _, new = both({"planned_sites": 20}, {"n_sites_2017": 33},
                  "Sites 20 or more (Target: up to 1 subject/site/month).", "sites")
    assert by_field(new, "sites") == [] and new.cleared[0].traps == ("lower_bound",)


def test_minimum_still_flags_a_registry_below_it():
    (m,) = by_field(run({"planned_sites": 20}, {"n_sites_2017": 5}, pages("at least 20 sites will open.")), "sites")
    assert "lower_bound" in m.traps


def test_card_took_the_evaluable_count_and_registry_has_the_enrolled_count():
    old, new = both({"planned_enrollment": 90}, {"enrollment": 300},
                    "We need 90 evaluable subjects. The estimated number of subjects to be enrolled (signed consent, "
                    "including screen failures) is 300 subjects.", "enrollment")
    assert len(old) == 1
    assert by_field(new, "enrollment") == [] and new.cleared[0].traps == ("count_definition",)


def test_registry_matching_another_funnel_count_is_doubtful_and_low_not_cleared():
    cases = [({"planned_enrollment": 62}, {"enrollment": 124}, "Our goal is to screen 124 subjects and recruit 62 individuals."),
             ({"planned_enrollment": 30}, {"enrollment": 100}, "We expect to screen up to 100 subjects to enroll 40 and complete 30."),
             ({"planned_enrollment": 100}, {"enrollment": 60}, "Enrollment: 100 subjects total (randomize 60 subjects) at two sites."),
             ({"planned_enrollment": 1462}, {"enrollment": 100},
              "The Pilot phase will operate at 6 sites for 1 year; with a target of recruitment of 102 participants. "
              "The full study will enrol 1462 participants.")]
    for card, reg, text in cases:
        old, new = both(card, reg, text, "enrollment")
        assert len(old) == 1 and "count_definition" not in old[0].traps, text
        (m,) = by_field(new, "enrollment")
        assert "count_definition" in m.traps and m.doubtful_reading and m.severity == "low", text


def test_number_without_a_funnel_role_is_not_a_count_definition():
    (m,) = by_field(run({"planned_enrollment": 43}, {"enrollment": 188},
                        pages("The study population will include 43 participants. Table 188 participants in the cohort.")),
                    "enrollment")
    assert "count_definition" not in m.traps


def test_unrelated_registry_number_is_not_cleared_as_a_funnel():
    res = run({"planned_enrollment": 200}, {"enrollment": 100},
              pages("We will enrol 200 patients. Each visit takes 100 minutes."))
    assert len(by_field(res, "enrollment")) == 1


def test_labelled_enrollment_field_is_found():
    (m,) = by_field(run({"planned_enrollment": 60}, {"enrollment": 20},
                        pages("Enrollment: 60 Mode of Advertising: Flyer")), "enrollment")
    assert m.evidence.page == 1 and "quote_not_found" not in m.traps


def test_multi_part_arm_counts_are_doubtful_and_low():
    for text in ("Subjects will be randomly assigned to a treatment sequence consisting of three treatment arms.",
                 "At entry, mothers will be randomized to one of three arms. In Step 2 infants enter two more arms.",
                 "Part B adds an open-label extension group for all subjects.",
                 "This protocol is comprised of three studies, each designed to test a different product."):
        old, new = both({"n_arms": 3}, {"n_arms": 6}, text, "arms")
        assert "multi_part_design" not in old[0].traps
        (m,) = by_field(new, "arms")
        assert "multi_part_design" in m.traps and m.doubtful_reading and m.severity == "low", text


def test_plain_parallel_arms_stay_a_normal_mismatch():
    (m,) = by_field(run({"n_arms": 3}, {"n_arms": 5}, pages("Patients are randomized to one of three arms.")), "arms")
    assert m.traps == () and m.severity == "medium"


def test_combined_phase_covering_both_values_is_low_and_quoted():
    text = "Compound Number: GSK716155 Development Phase III/IV Effective Date: 28-OCT-2015"
    old, new = both({"phase": "Phase 3"}, {"phase": "Phase 4"}, text, "phase")
    assert old[0].severity == "high"
    (m,) = by_field(new, "phase")
    assert m.severity == "low" and m.traps == ("combined_phase",) and "III/IV" in m.evidence.quote
    # the card already had the combined phase: an ordinary overlapping (low) mismatch, never cleared
    (m,) = by_field(run({"phase": "Phase 1/2"}, {"phase": "Phase 2"}, pages("A Phase 1 / 2, randomized trial")), "phase")
    assert m.severity == "low" and m.traps == ()
    # a different phase mentioned elsewhere does not soften a real conflict
    res = run({"phase": "Phase 3"}, {"phase": "Phase 1"}, pages("This Phase 3 study follows Phase 1 work."))
    assert by_field(res, "phase")[0].severity == "high"


def test_randomization_quote_about_a_previous_study_is_skipped():
    text = ("In the previous study, patients were randomized to placebo or drug. "
            "In this study, all patients receive open-label drug in a single-arm design.")
    res = run({"allocation": "Randomized"}, {"allocation": "Non-Randomized"}, pages(text))
    (m,) = by_field(res, "randomized")
    assert "single-arm" in m.evidence.quote.lower() or "single arm" in m.evidence.quote.lower()
    only_prior = run({"allocation": "Randomized"}, {"allocation": "Non-Randomized"},
                     pages("In the previous study, patients were randomized to placebo or drug."))
    (m,) = by_field(only_prior, "randomized")
    assert m.traps == ("other_study",) and m.doubtful_reading and m.severity == "medium"


def test_networks_with_satellites_are_flagged():
    (m,) = by_field(run({"planned_sites": 9}, {"n_sites_2017": 25},
                        pages("Nine AsthmaNet Clinical Center partnerships (and their associated satellites) will participate.")),
                    "sites")
    assert "satellite_sites" in m.traps and m.doubtful_reading


def test_unknown_rules_rejected():
    import pytest
    with pytest.raises(ValueError):
        run(rules="v9")


def test_past_tense_citations_and_other_study_codes_mark_a_previous_study():
    for text in ("Patients with mucositis were randomized to 2 nights of eszopiclone or placebo (11). Pain improved.",
                 "Patients who were randomized to the observational arm of the CVT-301-005 study may be enrolled.",
                 "In a pilot, subjects were randomized to drug or placebo [4]."):
        (m,) = by_field(run({"allocation": "Randomized"}, {"allocation": "Non-Randomized"}, pages(text)), "randomized")
        assert m.traps == ("other_study",), text
    (m,) = by_field(run({"allocation": "Randomized"}, {"allocation": "Non-Randomized"},
                        pages("Subjects will be randomized 1:1 to drug or placebo.")), "randomized")
    assert m.traps == () and m.severity == "high"


def test_randomized_presentation_order_is_not_allocation():
    (m,) = by_field(run({"allocation": "Non-Randomized"}, {"allocation": "Randomized"},
                        pages("Stimuli are presented in a randomized order. Subjects will be randomized 2:1 to A or B.")), "randomized")
    assert "will be randomized 2:1" in m.evidence.quote and m.traps == ()


def test_reference_list_titles_are_previous_studies():
    (m,) = by_field(run({"allocation": "Non-Randomized"}, {"allocation": "Randomized"},
                        pages("7) Smith J. Pain in fibromyalgia. A double-blind randomized trial. Clin Rheumat 1993;12:186-191.")), "randomized")
    assert m.traps == ("other_study",)


def test_any_hit_on_a_reference_page_is_a_previous_study():
    refs = ("1. Roth T, et al. Sleep 2009;32:1. 2. Lee A, et al. Pain 2010;5:2. 3. Kim B. A randomized, placebo-controlled, "
            "2-way crossover polysomnography study of a new drug in many patients. Arthritis Care Res 2012;62:5.")
    (m,) = by_field(run({"allocation": "Non-Randomized"}, {"allocation": "Randomized"}, pages(refs)), "randomized")
    assert m.traps == ("other_study",)
