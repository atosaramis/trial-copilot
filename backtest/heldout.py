"""Score the held-out set ONCE with the frozen rule (registry data only, no model calls).

    python -m backtest.heldout --root .. --lar36 /path/to/lar36 --out ../backtest-heldout

Checks the addendum sha256 against the value recorded in prep/MANIFEST.md, and the frozen model file
against the addendum, before any held-out outcome is read.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pickle
import re
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from backtest.analyze import LABEL_COLS, REG_COLS, auc_ci, calibration, load_module, logit

ADDENDUM_SHA = "efa4ad819bfb97721ff3d6e8e2cbe61444d4df4ebf3125eca7a8fd966eb40dc4"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def frozen_predict(pA: np.ndarray, fm: dict) -> np.ndarray:
    assert fm["features"] == ["logit_A"], "the locked rule uses A's score only"
    z = (logit(pA) - fm["scaler_mean"]["logit_A"]) / fm["scaler_scale"]["logit_A"]
    return 1 / (1 + np.exp(-(fm["intercept"] + fm["coef_standardized"]["logit_A"] * z)))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--lar36", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    add = a.root / "preregistration-addendum.md"
    assert sha(add) == ADDENDUM_SHA, "addendum changed"
    assert ADDENDUM_SHA in (a.root / "prep/MANIFEST.md").read_text(), "addendum hash not in MANIFEST"
    fm_path = a.root / "backtest-tuning/frozen_model.json"
    m = re.search(r"frozen_model\.json, sha256\s+([0-9a-f]{64})", add.read_text())
    assert m and sha(fm_path) == m.group(1), "frozen model file does not match the addendum"
    fm = json.loads(fm_path.read_text())

    # Unseal: held-out labels are read here, once.
    coh = pd.read_csv(a.root / "prep/cohort_1436.csv", usecols=LABEL_COLS)
    coh = coh[coh.split == "heldout"].set_index("nct_id").sort_index()
    assert len(coh) == 873
    ids = list(coh.index)
    strict = load_module(a.root / "tests/label-rule/strict_label.py", "strict_label").strict
    y = coh.label_poor_enrollment.astype(int).values
    ys = np.array([int(strict(int(p), w)[0]) for p, w in zip(y, coh.why_stopped)])
    near = (pd.to_datetime(coh.protocol_doc_date) <= pd.to_datetime(coh.start_date) + pd.Timedelta(days=31)).values

    reg = pd.read_pickle(a.lar36 / "data/lar36_2017.pkl")[REG_COLS].set_index("nct_id").loc[ids]
    base = load_module(a.lar36 / "scripts/13_baseline.py", "baseline13")
    mA, medA = pickle.load(open(a.lar36 / "data/baseline_split.pkl", "rb"))
    xa, _ = base.X(reg, medA)
    pA = mA.predict_proba(xa)[:, 1]
    pB = frozen_predict(pA, fm)
    cl = reg.lead_sponsor.fillna("unknown").values

    def block(mask, yy):
        return {"n": int(mask.sum()), "events": int(yy[mask].sum()),
                "A": {"auc": auc_ci(yy[mask], pA[mask], cl[mask]), "calibration": calibration(yy[mask], pA[mask])},
                "B": {"auc": auc_ci(yy[mask], pB[mask], cl[mask], s2=pA[mask]),
                      "calibration": calibration(yy[mask], pB[mask])}}

    allm = np.ones(len(y), bool)
    res = {"addendum_sha256": ADDENDUM_SHA, "frozen_model_sha256": sha(fm_path),
           "n": 873, "events": int(y.sum()), "events_strict": int(ys.sum()), "base_rate": round(float(y.mean()), 4),
           "primary": block(allm, y), "strict_label": block(allm, ys), "near_start": block(near, y),
           "rank_identity_check": bool(np.all(np.argsort(pA, kind="stable") == np.argsort(pB, kind="stable"))),
           "extraction_accuracy": "not run: no held-out protocol was extracted (the locked rule uses no protocol feature)"}
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "heldout_summary.json").write_text(json.dumps(res, indent=1, default=float))
    p = res["primary"]
    print(json.dumps({"events": res["events"], "A_auc": p["A"]["auc"], "B_auc": p["B"]["auc"],
                      "A_cal": {k: p["A"]["calibration"][k] for k in ("mean_predicted", "observed_rate", "calibration_slope", "calibration_intercept_in_the_large", "log_loss", "top10pct")},
                      "B_cal": {k: p["B"]["calibration"][k] for k in ("mean_predicted", "observed_rate", "calibration_slope", "calibration_intercept_in_the_large", "log_loss", "top10pct")}}, indent=1, default=float))


if __name__ == "__main__":
    main()
