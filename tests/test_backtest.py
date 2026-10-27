import json

import pytest

from backtest import run


def test_runner_refuses_heldout(tmp_path):
    with pytest.raises(SystemExit):
        run.main(["--cohort", "x.csv", "--pdf-dir", ".", "--pools", ".", "--out", str(tmp_path), "--split", "heldout"])


def test_tuning_ids_reads_only_tuning(tmp_path):
    p = tmp_path / "c.csv"
    p.write_text("nct_id,split,label_poor_enrollment\nNCT1,tuning,1\nNCT2,heldout,0\nNCT3,tuning,0\n")
    assert sorted(run.tuning_ids(p)) == ["NCT1", "NCT3"]


def test_done_trial_is_skipped_without_calls(tmp_path):
    class A:
        out = tmp_path
    t = tmp_path / "trials" / "NCT9"
    t.mkdir(parents=True)
    (t / "result.json").write_text(json.dumps({"nct_id": "NCT9", "status": "ok", "cost_usd": 0.01}))
    r = run.run_trial("NCT9", A, client=None, log=lambda _: None)
    assert r["skipped"] and r["status"] == "ok"


def test_retryable_errors():
    assert run.is_retryable("RateLimitError: 429 too many")
    assert run.is_retryable("MuseError: APIStatusError 503")
    assert not run.is_retryable("MuseError: BadRequestError 400 context length")


def test_limiter_counts_requests():
    lim = run.Limiter(rpm=3, tpm=10_000)
    for _ in range(3):
        lim.acquire(10)
    assert len(lim.events) == 3


def test_features_from_risk():
    f = run.features({"required_biomarker": "EGFR", "clinic_visits_first_12_weeks": 7},
                     {"risk": {"comparable_trials": {"rate": 0.1, "n": 50, "events": 5},
                               "site_pace": {"patients_per_site_per_month": 0.4}}})
    assert f["pace"] == 0.4 and f["comparable_rate"] == 0.1 and f["clinic_visits_days_1_85"] == 7
