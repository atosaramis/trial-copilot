"""Auto-grading mismatches against the 2020 and 2023 registry versions."""
from pathlib import Path

from app.mismatch import autograde as ag
from app.mismatch.finder import Evidence, Mismatch

ROOT = Path(__file__).resolve().parents[1]
STATED = Evidence(3, "…50 sites…", "stated")


def mm(field="sites", p=50, r=10, traps=()):
    return Mismatch("NCT00000001", field, p, r, "high", "protocol_higher", tuple(traps), STATED)


def snaps(*vals, field="n_sites", **extra):
    return [ag.Snapshot(d, **{field: v}, **extra) for d, v in zip(("2020-01-01", "2023-01-02"), vals) if v is not None]


def test_sites_categories():
    assert ag.grade(mm(), snaps(48, 50)).category == "caught_up"
    assert ag.grade(mm(p=20, r=5), snaps(50, 50)).category == "caught_up"           # passed the protocol number
    assert ag.grade(mm(), snaps(25, 30)).category == "partly_caught_up"
    assert ag.grade(mm(), snaps(10, 11)).category == "never_changed"
    assert ag.grade(mm(p=35, r=65), snaps(73, 73)).category == "never_changed"      # within 20% of 65
    assert ag.grade(mm(p=35, r=65), snaps(90, 95)).category == "changed_other_way"
    g = ag.grade(mm(), [])
    assert g.category == "ambiguous" and not g.settled and "no later" in g.reason


def test_doubtful_reading_is_ambiguous_unless_the_registry_later_matches():
    for t in ("planning_assumption", "quote_not_found", "range", "registry_value_in_protocol", "evaluable_count"):
        g = ag.grade(mm(traps=(t,)), snaps(10, 10))
        assert g.category == "ambiguous" and "record alone: never_changed" in g.reason
    assert ag.grade(mm(traps=("quote_not_found",)), snaps(50)).category == "caught_up"
    assert ag.grade(mm(p=70, r=1, traps=("registry_placeholder",)), snaps(1, 1)).category == "never_changed"


def test_enrollment_uses_planned_numbers_only():
    m = mm("enrollment", 200, 100)
    later = [ag.Snapshot("2020-01-01", enrollment=200, enrollment_type="Anticipated")]
    assert ag.grade(m, later).category == "caught_up"
    later = [ag.Snapshot("2020-01-01", enrollment=100, enrollment_type="Anticipated")]
    assert ag.grade(m, later).category == "never_changed"
    later = [ag.Snapshot("2020-01-01", enrollment=190, enrollment_type="Actual")]
    g = ag.grade(m, later)
    assert g.category == "ambiguous" and "closer to the protocol" in g.reason


def test_design_fields():
    ph = Mismatch("NCT1", "phase", "Phase 3", "Phase 2", "high", "differs")
    assert ag.grade(ph, [ag.Snapshot("2020-01-01", phase="Phase 3")]).category == "caught_up"
    assert ag.grade(ph, [ag.Snapshot("2020-01-01", phase="Phase 2")]).category == "never_changed"
    assert ag.grade(ph, [ag.Snapshot("2020-01-01", phase="Phase 4")]).category == "changed_other_way"
    rz = Mismatch("NCT1", "randomized", "Randomized", "Non-Randomized", "high", "differs")
    assert ag.grade(rz, [ag.Snapshot("2020-01-01", allocation="Randomized")]).category == "caught_up"
    ar = mm("arms", 3, 2)
    assert ag.grade(ar, [ag.Snapshot("2020-01-01", n_arms=2)]).category == "never_changed"


def test_categories_are_honest_words():
    words = " ".join(ag.CATEGORIES).lower() + (ROOT / "app/mismatch/autograde.py").read_text().lower()
    for bad in ("non-compliance", "noncompliance", "violation", "fraud"):
        assert bad not in words


def test_load_snapshot_reads_design_fields_only(tmp_path):
    (tmp_path / "studies.txt").write_text(
        "nct_id|overall_status|phase|enrollment|enrollment_type|number_of_arms\n"
        "NCT1|Terminated|Phase 2|120|Actual|2\nNCT9|Completed|Phase 3|5|Actual|1\n")
    (tmp_path / "calculated_values.txt").write_text("id|nct_id|number_of_facilities\n1|NCT1|14\n")
    (tmp_path / "designs.txt").write_text("id|nct_id|allocation\n1|NCT1|Randomized\n")
    (tmp_path / "countries.txt").write_text("id|nct_id|name|removed\n1|NCT1|France|f\n2|NCT1|Spain|t\n3|NCT1|Italy|\n")
    s = ag.load_snapshot(tmp_path, "2020-01-01", ["NCT1"])
    assert set(s) == {"NCT1"}
    assert s["NCT1"] == ag.Snapshot("2020-01-01", 14.0, 2.0, 120.0, "Actual", "Phase 2", "Randomized", 2.0)
    src = (ROOT / "app/mismatch/autograde.py").read_text()
    assert "overall_status" not in src and "why_stopped" not in src
