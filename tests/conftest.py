"""Shared fixtures: tiny synthetic registry pools (no real data in the repo)."""
import pandas as pd
import pytest


def _sim(i, cond, phase, outcome, enroll, sites, start, pc, title=None, why=None, itv="Drug: X",
         lead="Industry", criteria=""):
    return {"nct_id": f"NCT{i:08d}", "title": title or f"{cond} study {i}", "phase": phase,
            "status_2017": "Completed" if outcome == "completed" else "Terminated",
            "why_stopped_2017": why, "start_date": pd.Timestamp(start),
            "primary_completion_date": pd.Timestamp(pc), "completion_date": pd.Timestamp(pc),
            "enrollment": enroll, "enrollment_type": "Actual", "n_arms": 2, "primary_purpose": "Treatment",
            "allocation": "Randomized", "masking": "Open Label", "intervention_model": "Parallel",
            "conditions": cond, "mesh_conditions": cond, "interventions": itv, "mesh_interventions": "",
            "keywords": "", "lead_sponsor": "Co", "lead_class": lead, "n_sites_2017": sites,
            "n_countries": 1, "countries": "United States", "has_us_facility": "t", "gender": "All",
            "minimum_age": "18 Years", "maximum_age": "N/A", "healthy_volunteers": "No",
            "criteria": criteria, "outcome_2017": outcome,
            "label_poor_enrollment": int(outcome == "terminated_poor_enrollment")}


@pytest.fixture
def pools(tmp_path):
    sim = []
    i = 1
    # 40 myeloma phase 2 trials: 4 poor-enrollment stops, 2 other stops, 34 completed.
    for k in range(40):
        outcome = ("terminated_poor_enrollment" if k < 4 else "terminated_other" if k < 6 else "completed")
        sim.append(_sim(i, "Multiple Myeloma", "Phase 2", outcome, 50 + k * 5, 1 + k % 10,
                        "2010-01-01", "2012-01-01", why="slow accrual" if k < 4 else None,
                        itv="Drug: Bortezomib" if k % 2 else "Drug: Lenalidomide"))
        i += 1
    for k in range(20):  # COPD phase 3, 1 event
        sim.append(_sim(i, "COPD", "Phase 3", "terminated_poor_enrollment" if k == 0 else "completed",
                        400, 40, "2011-01-01", "2013-01-01", criteria="eosinophil count >= 300" if k < 5 else ""))
        i += 1
    comp = [{"nct_id": f"NCT9{k:07d}", "title": f"Myeloma trial {k}", "phase": "Phase 2" if k < 3 else "Phase 3",
             "status_2017": "Recruiting", "start_date": pd.Timestamp("2016-01-01"),
             "primary_completion_date": pd.Timestamp("2019-01-01"), "enrollment_anticipated": 100,
             "conditions": "Multiple Myeloma", "mesh_conditions": "Multiple Myeloma", "interventions": "Drug: Y",
             "mesh_interventions": "", "keywords": "", "lead_class": "Industry", "n_sites_2017": 10 + k,
             "n_countries": 1, "countries": "United States" if k < 4 else "France", "has_us_facility": "t",
             "minimum_age": "18 Years", "maximum_age": "N/A"} for k in range(5)]
    # The audited trial itself is also open in Jan 2017.
    own = dict(comp[0], nct_id="NCT02720510", title="Audited myeloma trial", n_sites_2017=5)
    comp.append(own)
    cohort = [{k: own.get(k) for k in own} | {"enrollment": 112, "enrollment_type": "Anticipated", "n_arms": 2,
                                               "primary_purpose": "Treatment", "allocation": "Randomized",
                                               "masking": "Open Label", "intervention_model": "Parallel",
                                               "lead_sponsor": "Co", "gender": "All", "healthy_volunteers": "No",
                                               "criteria": "", "start_date": pd.Timestamp("2016-06-01"),
                                               "primary_completion_date": pd.Timestamp("2021-02-01")}]
    for c in cohort:
        c.pop("enrollment_anticipated", None)
    pd.DataFrame(sim).to_parquet(tmp_path / "similar_pool_2017.parquet", index=False)
    pd.DataFrame(comp).to_parquet(tmp_path / "competing_pool_2017.parquet", index=False)
    pd.DataFrame(cohort).to_parquet(tmp_path / "cohort_1436_registry_2017.parquet", index=False)
    return tmp_path
