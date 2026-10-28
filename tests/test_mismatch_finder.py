"""Deterministic protocol-vs-registry finder: comparisons, severities, quotes and known traps."""
from app.mismatch import finder as f

FILL = "The study drug is given orally once daily with food and water at the clinic. " * 4
REG = {"phase": "Phase 2", "allocation": "Randomized", "n_arms": 2, "enrollment": 80,
       "enrollment_type": "Anticipated", "n_sites_2017": 20, "n_countries": 2}
CARD = {"phase": "Phase 2", "allocation": "Randomized", "n_arms": 2, "planned_enrollment": 80,
        "planned_sites": 20, "planned_countries": 2}


def pages(*texts):
    return [FILL + t for t in texts]


def run(card=None, reg=None, pg=None, rules=f.DEFAULT_RULES):
    return f.find_mismatches("NCT00000001", CARD | (card or {}), REG | (reg or {}), pg, rules=rules)


def by_field(res, field):
    return [m for m in res.mismatches if m.field == field]


def test_agreeing_record_has_no_mismatch_and_counts_compared_fields():
    res = run(pg=pages("Approximately 80 subjects at 20 sites in 2 countries."))
    assert res.mismatches == [] and res.cleared == []
    assert set(res.compared) == set(f.FIELDS)


def test_site_tolerance_is_max_of_two_or_twenty_percent():
    assert run({"planned_sites": 22}).mismatches == []          # within 2
    assert run({"planned_sites": 24}).mismatches == []          # within 20% of 20
    assert by_field(run({"planned_sites": 25}), "sites")


def test_site_mismatch_carries_page_and_quote_and_severity():
    res = run({"planned_sites": 50}, pg=pages("Background.", "The trial will run at approximately 50 investigational sites."))
    (m,) = by_field(res, "sites")
    assert (m.severity, m.direction, m.evidence.page, m.evidence.kind) == ("high", "protocol_higher", 2, "stated")
    assert "50 investigational sites" in m.evidence.quote and m.traps == ()


def test_number_words_and_labelled_fields_are_found():
    res = run({"planned_sites": 30}, pg=pages("Number of sites: thirty"))
    assert by_field(res, "sites")[0].evidence.kind == "stated"
    res = run({"planned_enrollment": 200}, pg=pages("Sample size: N = 200 randomized."))
    assert by_field(res, "enrollment")[0].evidence.page == 1


def test_range_that_covers_the_registry_is_cleared_not_flagged():
    res = run({"planned_sites": 25}, {"n_sites_2017": 19}, pages("Approximately 80 subjects at approximately 20-25 study sites."))
    assert by_field(res, "sites") == []
    assert res.cleared and res.cleared[0].traps == ("range",)


def test_range_that_misses_the_registry_stays_but_is_doubtful():
    res = run({"planned_sites": 60}, {"n_sites_2017": 10}, pages("At 50 to 60 sites."))
    (m,) = by_field(res, "sites")
    assert "range" in m.traps and m.doubtful_reading and m.severity == "medium"


def test_statistical_planning_assumption_is_low_and_doubtful():
    res = run({"planned_sites": 40}, {"n_sites_2017": 60},
              pages("Estimates of accrual for purposes of statistical planning assume 40 enrollment sites averaging 5 subjects per year."))
    (m,) = by_field(res, "sites")
    assert m.evidence.kind == "planning_assumption" and m.severity == "low" and m.doubtful_reading


def test_one_site_placeholder_registry_entry_is_low_but_not_a_reading_problem():
    res = run({"planned_sites": 70}, {"n_sites_2017": 1}, pages("Approximately 70 centers worldwide."))
    (m,) = by_field(res, "sites")
    assert m.traps == ("registry_placeholder",) and m.severity == "low" and not m.doubtful_reading


def test_card_value_missing_from_text_is_flagged():
    (m,) = by_field(run({"planned_sites": 45}, pg=pages("Several sites will take part.")), "sites")
    assert m.evidence.kind == "not_found" and "quote_not_found" in m.traps


def test_registry_number_also_in_protocol_and_evaluable_counts():
    pg = pages("A total of 120 patients will be enrolled so that 100 evaluable patients complete the study.")
    (m,) = by_field(run({"planned_enrollment": 100}, {"enrollment": 120}, pg, rules="v2"), "enrollment")
    assert {"evaluable_count", "registry_value_in_protocol"} <= set(m.traps)
    assert m.doubtful_reading
    res = run({"planned_enrollment": 100}, {"enrollment": 120}, pg)          # v3: a funnel, not a mismatch
    assert by_field(res, "enrollment") == [] and res.cleared[0].traps == ("count_definition",)


def test_enrollment_severity_by_ratio():
    sev = {p: by_field(run({"planned_enrollment": p}, pg=pages(f"{p} participants")), "enrollment")[0].severity
           for p in (100, 130, 170)}
    assert sev == {100: "low", 130: "medium", 170: "high"}
    assert run({"planned_enrollment": 87}).mismatches == []     # within 10%


def test_scanned_or_garbled_text_gives_no_quote_and_no_reading_trap(tmp_path):
    garbled = tmp_path / "g.txt"
    garbled.write_text("\f".join(["A dv isort odis cusss pecificso fs u bj ec t off -siteov e r nigh " * 20] * 3))
    assert f.load_pages(garbled) == []
    scan = tmp_path / "s.txt"
    scan.write_text("\f\f\f")
    assert f.load_pages(scan) == []
    good = tmp_path / "ok.txt"
    good.write_text("Protocol title page. " + FILL + "\f" + FILL + "At approximately 70 centers.")
    assert len(f.load_pages(good)) == 2
    (m,) = by_field(run({"planned_sites": 70}, {"n_sites_2017": 30}, f.load_pages(scan)), "sites")
    assert m.evidence.kind == "no_text" and m.traps == ()


def test_phase_neighbours_are_low_and_disjoint_phases_high():
    (m,) = by_field(run({"phase": "Phase 2/Phase 3"}), "phase")
    assert m.severity == "low"
    (m,) = by_field(run({"phase": "Phase 3"}), "phase")
    assert m.severity == "high"
    assert f.normalize_phase("Phase II") == f.normalize_phase("phase 2") == frozenset({"2"})
    assert f.normalize_phase("Phase 2 (pilot)") == frozenset({"2"})
    assert f.normalize_phase("N/A") == frozenset({"na"})


def test_randomized_conflict_is_high_and_quotes_the_design():
    res = run({"allocation": "Non-Randomized"}, pg=pages("This is a randomized, double-blind study."))
    (m,) = by_field(res, "randomized")
    assert m.severity == "high" and "randomized" in m.evidence.quote
    assert f.card_randomized("Single group") is False and f.registry_randomized("N/A") is False


def test_arms_and_countries_are_low_noise_fields():
    (m,) = by_field(run({"n_arms": 3}), "arms")
    assert m.severity == "low" and "quote_not_found" not in m.traps
    (m,) = by_field(run({"planned_countries": 10}, pg=pages("in 10 countries")), "countries")
    assert m.severity == "medium"


def test_missing_values_are_not_compared():
    res = run({"planned_sites": None, "planned_countries": None}, {"phase": None})
    assert "sites" not in res.compared and "countries" not in res.compared and "phase" not in res.compared
