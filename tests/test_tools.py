import pytest

from app.tools import FORBIDDEN_COLS, TOOL_SPECS, RegistryTools, ToolError


def test_comparable_search_counts_and_filters(pools):
    t = RegistryTools(pools, exclude_nct="NCT02720510", target_enrollment=112)
    r = t.search_comparable_trials(["myeloma"], ["Phase 2"])
    assert r["n_matched"] == 40
    assert r["outcome_counts_2017"]["terminated_poor_enrollment"] == 4
    assert r["poor_enrollment_share"] == 0.1
    assert len(r["top_25"]) == 25
    # closest planned size first
    assert abs(r["top_25"][0]["enrollment"] - 112) <= 5
    r2 = t.search_comparable_trials(["myeloma"], ["Phase 2"], intervention_terms=["bortezomib"])
    assert r2["n_matched"] == 20
    r3 = t.search_comparable_trials(["COPD"], ["Phase 3"], biomarker_terms=["eosinophil"])
    assert r3["n_matched"] == 5
    assert r3["result_id"] == "S3"
    assert set(t.results) == {"S1", "S2", "S3"}


def test_phase_synonyms_and_bad_args(pools):
    t = RegistryTools(pools)
    assert t.search_comparable_trials(["myeloma"], "phase ii")["n_matched"] == 40
    with pytest.raises(ToolError):
        t.search_comparable_trials([])
    with pytest.raises(ToolError):
        t.search_comparable_trials(["myeloma"], ["Phase 9"])
    with pytest.raises(ToolError):
        t.search_comparable_trials(["myeloma'; DROP TABLE x; --"])
    with pytest.raises(ToolError):
        t.search_comparable_trials(["myeloma"], enrollment_range="big")
    with pytest.raises(ToolError):
        t.call("run_sql", {})


def test_competing_excludes_audited_trial(pools):
    t = RegistryTools(pools, exclude_nct="NCT02720510")
    r = t.count_competing_trials(["myeloma"])
    assert r["n_recruiting"] == 5
    assert r["snapshot_date"] == "2017-01-05"
    assert t.count_competing_trials(["myeloma"], ["Phase 2"], ["United States"])["n_recruiting"] == 3
    assert RegistryTools(pools).count_competing_trials(["myeloma"])["n_recruiting"] == 6


def test_get_trial_never_returns_later_columns(pools):
    t = RegistryTools(pools, exclude_nct="NCT02720510")
    rec = t.get_trial("NCT00000001")
    assert rec["pool"] == "similar_pool" and rec["outcome_2017"] == "terminated_poor_enrollment"
    assert not (set(rec) & FORBIDDEN_COLS)
    with pytest.raises(ToolError):
        t.get_trial("NCT02720510")  # the audited trial is never its own comparable
    assert t.get_trial("NCT12345678")["found"] is False


def test_registry_2017_for_code_only(pools):
    t = RegistryTools(pools)
    reg = t.registry_2017("NCT02720510")
    assert reg["n_sites_2017"] == 5 and reg["enrollment"] == 112
    assert not (set(reg) & FORBIDDEN_COLS)


def test_tool_specs_require_a_reason():
    assert {s["function"]["name"] for s in TOOL_SPECS} == {"search_comparable_trials",
                                                           "count_competing_trials", "get_trial"}
    for s in TOOL_SPECS:
        assert "reason" in s["function"]["parameters"]["required"]


def test_tools_read_only_the_frozen_2017_pools():
    from app.tools import COMPETING_COLS, POOL_FILES, SIMILAR_COLS, TRIAL_COLS
    assert all("_2017." in f for f in POOL_FILES.values())
    assert not any("cohort_1436.csv" in f for f in POOL_FILES.values())
    for cols in (SIMILAR_COLS, COMPETING_COLS, TRIAL_COLS):
        assert not (set(cols) & FORBIDDEN_COLS)
        assert not any("2020" in c or "2023" in c for c in cols)


def test_terms_match_at_word_start(pools):
    t = RegistryTools(pools)
    assert t.search_comparable_trials(["yeloma"], ["Phase 2"])["n_matched"] == 0
    assert t.search_comparable_trials(["MYELOMA"], ["Phase 2"])["n_matched"] == 40
    assert t.search_comparable_trials(["copd"])["n_matched"] == 20


def test_hyphen_prefix_is_not_a_word_start(tmp_path):
    import pandas as pd

    from tests.conftest import _sim
    rows = [_sim(1, "Non-Small Cell Lung Cancer", "Phase 2", "completed", 50, 1, "2010-01-01", "2011-01-01"),
            _sim(2, "Small Cell Lung Cancer", "Phase 2", "completed", 50, 1, "2010-01-01", "2011-01-01"),
            _sim(3, "NSCLC", "Phase 2", "completed", 50, 1, "2010-01-01", "2011-01-01")]
    pd.DataFrame(rows).to_parquet(tmp_path / "similar_pool_2017.parquet", index=False)
    for f in ("competing_pool_2017.parquet", "cohort_1436_registry_2017.parquet"):
        pd.DataFrame([{"nct_id": "NCT1"}]).to_parquet(tmp_path / f, index=False)
    t = RegistryTools(tmp_path)
    assert t.search_comparable_trials(["small cell lung cancer"])["n_matched"] == 1
    assert t.search_comparable_trials(["SCLC"])["n_matched"] == 0
    assert t.search_comparable_trials(["non-small cell"])["n_matched"] == 1


def test_countries_allow_long_lists(pools):
    t = RegistryTools(pools)
    many = ["United States", "France", "Spain", "Germany", "Greece", "Turkey", "Ukraine", "Netherlands",
            "Korea, Republic of", "United Kingdom"]
    assert t.count_competing_trials(["myeloma"], countries=many)["n_recruiting"] == 6
    with pytest.raises(ToolError):
        t.search_comparable_trials([f"term{i}" for i in range(9)])
