"""Pre-registered tuning-set analysis (see backtest-tuning/analysis_plan.md). Tuning set only.

    python -m backtest.analyze --out ../backtest-tuning --cohort ../prep/cohort_1436.csv \
        --lar36 /path/to/lar36 --strict ../tests/label-rule/strict_label.py

Writes summary.json (aggregates only, no protocol text) and frozen_model.json to --out.
"""
from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
import pickle
import re
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss, roc_auc_score
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

POOL_RATE = 2359 / 56509
CANDIDATES = ["pace", "biomarker", "visits", "comp_rate"]
NEG = re.compile(r"^\s*(none|no|not required|not applicable|n/?a|null|-)\b", re.I)
REG_COLS = ["nct_id", "phase", "enroll_anticipated", "n_sites", "n_countries", "months_since_start",
            "months_to_pc", "elig_chars", "n_criteria", "industry", "oncology", "us_site",
            "lead_sponsor", "allocation", "masking", "n_arms"]  # registry fields only, no outcome columns
LABEL_COLS = ["nct_id", "split", "label_poor_enrollment", "why_stopped", "start_date",
              "protocol_doc_date", "protocol_doc_type"]


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def transform(raw: pd.DataFrame) -> pd.DataFrame:
    f = pd.DataFrame(index=raw.index)
    f["pace"] = np.log(raw["pace"].astype(float).clip(0.001, 20))
    bt = raw["required_biomarker_text"]
    f["biomarker"] = bt.map(lambda s: np.nan if s is None or (isinstance(s, float) and np.isnan(s))
                            else (0.0 if (not str(s).strip() or NEG.match(str(s))) else 1.0))
    f["visits"] = raw["clinic_visits_days_1_85"].astype(float).clip(0, 60)
    f["visits_sensitivity"] = raw["contacts_screening_to_day_85"].astype(float).clip(0, 60)
    f["comp_rate"] = raw["comparable_rate"].astype(float)
    return f


def impute(f: pd.DataFrame, extracted: pd.Series) -> tuple[pd.DataFrame, dict]:
    med = {}
    out = f.copy()
    for c in f.columns:
        if c == "biomarker":
            med[c] = 0.0
        elif c == "comp_rate":
            med[c] = POOL_RATE  # no comparable set (or no card): the pool rate, as planned
        else:
            med[c] = float(f[c].median())
        out[c] = f[c].fillna(med[c])
    return out, med


def auc_ci(y, s, clusters, reps=2000, seed=0, s2=None):
    """AUC (and optionally the paired difference s - s2) with a lead-sponsor cluster bootstrap."""
    y, s = np.asarray(y), np.asarray(s)
    s2 = None if s2 is None else np.asarray(s2)
    point = roc_auc_score(y, s)
    d_point = None if s2 is None else point - roc_auc_score(y, s2)
    cl = pd.Series(clusters).astype(str).values
    uniq = np.unique(cl)
    idx = {c: np.where(cl == c)[0] for c in uniq}
    rng = np.random.default_rng(seed)
    a, d = [], []
    for _ in range(reps):
        pick = rng.choice(uniq, len(uniq), replace=True)
        ii = np.concatenate([idx[c] for c in pick])
        if y[ii].min() == y[ii].max():
            continue
        v = roc_auc_score(y[ii], s[ii])
        a.append(v)
        if s2 is not None:
            d.append(v - roc_auc_score(y[ii], s2[ii]))
    out = {"auc": round(point, 4), "ci95": [round(float(np.percentile(a, 2.5)), 4),
                                            round(float(np.percentile(a, 97.5)), 4)], "reps_used": len(a)}
    if s2 is not None:
        out["diff_vs_A"] = round(d_point, 4)
        out["diff_ci95"] = [round(float(np.percentile(d, 2.5)), 4), round(float(np.percentile(d, 97.5)), 4)]
    return out


def calibration(y, p):
    y, p = np.asarray(y), np.asarray(p)
    cal = LogisticRegression(C=1e6, max_iter=5000).fit(logit(p).reshape(-1, 1), y)
    # intercept-in-the-large: offset model with slope fixed at 1
    lo, hi, lp = -10.0, 10.0, logit(p)
    for _ in range(100):  # bisection: the shift b with mean(sigmoid(logit p + b)) = observed rate
        mid = (lo + hi) / 2
        if np.mean(1 / (1 + np.exp(-(lp + mid)))) < y.mean():
            lo = mid
        else:
            hi = mid
    citl = (lo + hi) / 2
    order = np.argsort(p)
    bins = np.array_split(order, 10)
    k = max(1, int(round(0.10 * len(p))))
    top = np.argsort(-p)[:k]
    return {
        "log_loss": round(log_loss(y, p), 5), "brier": round(float(np.mean((p - y) ** 2)), 5),
        "mean_predicted": round(float(p.mean()), 4), "observed_rate": round(float(y.mean()), 4),
        "calibration_slope": round(float(cal.coef_[0][0]), 3),
        "calibration_intercept_in_the_large": round(float(citl), 3),
        "bins_10": [{"n": len(b), "mean_predicted": round(float(p[b].mean()), 4),
                     "observed": round(float(y[b].mean()), 4), "events": int(y[b].sum())} for b in bins],
        "top10pct": {"n": k, "events": int(y[top].sum()), "precision": round(float(y[top].mean()), 4)},
    }


def model_b():
    return make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=5000))


def oof(X, y, seed):
    p = np.zeros(len(y))
    for tr, te in StratifiedKFold(5, shuffle=True, random_state=seed).split(X, y):
        p[te] = model_b().fit(X[tr], y[tr]).predict_proba(X[te])[:, 1]
    return p


def agree(card: dict | None, r: pd.Series) -> dict:
    out = {}
    if not card:
        return out
    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    e, re_ = num(card.get("planned_enrollment")), num(r.enroll_anticipated)
    if e and re_:
        out["enrollment"] = abs(e - re_) <= 0.10 * re_
    s, rs = num(card.get("planned_sites")), num(r.n_sites)
    if s and rs:
        out["sites"] = abs(s - rs) <= max(2, 0.20 * rs)
    if card.get("phase") and isinstance(r.phase, str):
        out["phase"] = str(card["phase"]).replace(" ", "").lower() == r.phase.replace(" ", "").lower()
    if card.get("allocation") and isinstance(r.allocation, str):
        out["randomized"] = ("non" not in str(card["allocation"]).lower() and "single" not in
                             str(card["allocation"]).lower() and "random" in str(card["allocation"]).lower()) == \
                            (r.allocation == "Randomized")
    if card.get("masking") and isinstance(r.masking, str):
        out["open_label"] = ("open" in str(card["masking"]).lower() or "none" in str(card["masking"]).lower()) == \
                            ("open" in r.masking.lower())
    n, rn = num(card.get("n_arms")), num(r.n_arms)
    if n and rn:
        out["n_arms"] = n == rn
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--cohort", type=Path, required=True)
    ap.add_argument("--lar36", type=Path, required=True)
    ap.add_argument("--strict", type=Path, required=True)
    a = ap.parse_args(argv)

    ids = json.loads((a.out / "order.json").read_text())["ids"]
    coh = pd.read_csv(a.cohort, usecols=LABEL_COLS)
    coh = coh[coh.split == "tuning"].set_index("nct_id").loc[ids]  # tuning rows only
    assert len(coh) == 563
    strict = load_module(a.strict, "strict_label").strict
    coh["y"] = coh.label_poor_enrollment.astype(int)
    coh["y_strict"] = [int(strict(int(p), w)[0]) for p, w in zip(coh.y, coh.why_stopped)]
    coh["near_start"] = (pd.to_datetime(coh.protocol_doc_date) <= pd.to_datetime(coh.start_date)
                         + pd.Timedelta(days=31))
    dt = coh.protocol_doc_type.fillna("").str.lower()
    coh["original"] = dt.str.contains(r"original|initial|v\. ?0\.0") | coh.near_start

    reg = pd.read_pickle(a.lar36 / "data/lar36_2017.pkl")[REG_COLS]
    reg = reg.set_index("nct_id").loc[ids]
    base = load_module(a.lar36 / "scripts/13_baseline.py", "baseline13")
    mA, medA = pickle.load(open(a.lar36 / "data/baseline_split.pkl", "rb"))
    xa, _ = base.X(reg.rename_axis("nct_id"), medA)
    pA = mA.predict_proba(xa)[:, 1]

    rows, ext = [], {}
    for n in ids:
        t = a.out / "trials" / n
        r = json.loads((t / "result.json").read_text()) if (t / "result.json").exists() else (
            json.loads((t / "failed.json").read_text()) if (t / "failed.json").exists() else {"status": "missing"})
        ext[n] = r
        f = r.get("features") or {}
        rows.append({"nct_id": n, **{k: f.get(k) for k in ("pace", "required_biomarker_text",
                     "clinic_visits_days_1_85", "contacts_screening_to_day_85", "comparable_rate")}})
    raw = pd.DataFrame(rows).set_index("nct_id")
    has_card = pd.Series({n: bool(ext[n].get("card")) for n in ids})
    feats = transform(raw)
    missing = {c: int(feats[c].isna().sum()) for c in feats.columns}
    fi, med = impute(feats, has_card)

    y, ys, cl = coh.y.values, coh.y_strict.values, reg.lead_sponsor.fillna("unknown").values
    la = logit(pA)

    # Extraction outcomes
    kinds = pd.Series({n: ext[n].get("kind") or ext[n].get("status") for n in ids}).value_counts().to_dict()
    status = pd.Series({n: ext[n].get("status") for n in ids}).value_counts().to_dict()
    no_card = int((~has_card).sum())
    stubs = sum(1 for n in ids if ext[n].get("kind") == "stub")
    found_by = {}
    for n in ids:
        cards = list((a.out / "trials" / n / "extract").glob("*/card.json"))
        fb = json.loads(cards[0].read_text())["source"].get("schedule", {}).get("found_by") if cards else None
        fb = fb or ("scan (pages 1-10)" if ext[n].get("kind") == "scan" else "none")
        found_by[fb] = found_by.get(fb, 0) + 1

    # Univariate AUCs (higher value = higher risk), both visit definitions
    uni = {}
    for c in ["pace", "biomarker", "visits", "visits_sensitivity", "comp_rate"]:
        m = feats[c].notna().values
        uni[c] = {"observed_only": auc_ci(y[m], feats[c].values[m], cl[m]) | {"n": int(m.sum()), "events": int(y[m].sum())},
                  "imputed_all": auc_ci(y, fi[c].values, cl)}
    uni["A_score"] = auc_ci(y, pA, cl)

    # Feature choice: 15 subsets of size 0-3, 20 x stratified 5-fold CV, mean log loss
    sel = []
    for k in range(0, 4):
        for sub in itertools.combinations(CANDIDATES, k):
            X = np.column_stack([la] + [fi[c].values for c in sub])
            ll = [log_loss(y, oof(X, y, s)) for s in range(20)]
            sel.append({"features": list(sub), "cv_log_loss": round(float(np.mean(ll)), 5),
                        "sd": round(float(np.std(ll)), 5)})
    best = min(s["cv_log_loss"] for s in sel)
    chosen = sorted([s for s in sel if s["cv_log_loss"] <= best + 0.0005],
                    key=lambda s: (len(s["features"]), s["cv_log_loss"]))[0]
    feats_b = chosen["features"]
    XB = np.column_stack([la] + [fi[c].values for c in feats_b])
    pB = oof(XB, y, 0)

    res = {"n": 563, "events": int(y.sum()), "events_strict": int(ys.sum()),
           "base_rate": round(float(y.mean()), 4), "base_rate_strict": round(float(ys.mean()), 4),
           "extraction": {"kind": kinds, "status": status, "no_card": no_card, "stubs": stubs,
                          "failure_rate_excl_stubs": round((no_card - stubs) / (563 - stubs), 4),
                          "schedule_found_by": found_by, "feature_missing": missing},
           "univariate": uni, "selection": sel, "chosen": chosen,
           "A_in_sample": {"auc": auc_ci(y, pA, cl), "calibration": calibration(y, pA)},
           "B_out_of_fold": {"auc": auc_ci(y, pB, cl, s2=pA), "calibration": calibration(y, pB)}}
    # Strict label
    res["strict_label"] = {"A": auc_ci(ys, pA, cl), "B_oof": auc_ci(ys, pB, cl, s2=pA)}
    # Visits sensitivity definition substituted into B (reported only)
    if "visits" in feats_b:
        Xs = np.column_stack([la] + [fi["visits_sensitivity" if c == "visits" else c].values for c in feats_b])
        res["visits_sensitivity_in_B"] = auc_ci(y, oof(Xs, y, 0), cl, s2=pA)
    # Near-start subgroup
    ns = coh.near_start.values
    res["near_start"] = {"n": int(ns.sum()), "events": int(y[ns].sum()),
                         "A": auc_ci(y[ns], pA[ns], cl[ns]), "B_oof": auc_ci(y[ns], pB[ns], cl[ns], s2=pA[ns]),
                         "univariate_observed": {c: (auc_ci(y[ns & feats[c].notna().values],
                                                            feats[c].values[ns & feats[c].notna().values],
                                                            cl[ns & feats[c].notna().values])
                                                     if y[ns & feats[c].notna().values].sum() > 1 else None)
                                                 for c in ["pace", "biomarker", "visits", "visits_sensitivity", "comp_rate"]}}
    # Extraction accuracy vs Jan 2017 registry
    acc = {}
    for grp, mask in (("original", coh.original.values), ("amended", ~coh.original.values)):
        tallies = {}
        for n, m in zip(ids, mask):
            if not m:
                continue
            for k, v in agree(ext[n].get("card"), reg.loc[n]).items():
                t = tallies.setdefault(k, [0, 0])
                t[0] += int(v)
                t[1] += 1
        acc[grp] = {"n_trials": int(mask.sum()),
                    **{k: {"agree": v[0], "compared": v[1], "rate": round(v[0] / v[1], 3)} for k, v in tallies.items()}}
    res["extraction_agreement_with_2017_registry"] = acc
    # Spend and time
    led = [json.loads(x) for x in (a.out / "spend_ledger.jsonl").read_text().splitlines()]
    res["spend_usd"] = round(sum(x["cost_usd"] for x in led), 4)
    res["search"] = {"capped": sum(1 for n in ids if ext[n].get("search_capped")),
                     "failed": sum(1 for n in ids if ext[n].get("search_status") == "failed"),
                     "median_steps": float(np.median([ext[n].get("search_steps") or 0 for n in ids if ext[n].get("card")]))}

    # Freeze B on all 563
    fin = model_b().fit(XB, y)
    sc, lr = fin[0], fin[-1]
    frozen = {"features": ["logit_A"] + feats_b, "chosen_by": chosen,
              "transforms": {"logit_A": "log(p/(1-p)) of the locked baseline_split.pkl probability, p clipped to [1e-6, 1-1e-6]",
                             "pace": "log(clip(patients_per_site_per_month, 0.001, 20))",
                             "biomarker": "1 if required_biomarker is non-empty and not a negation (none/no/not required/not applicable/n/a), else 0",
                             "visits": "clip(clinic_visits_first_12_weeks, 0, 60)",
                             "comp_rate": "comparable_trials.rate; no comparable set -> pool rate 2359/56509"},
              "imputation": {c: med[c] for c in feats_b},
              "scaler_mean": dict(zip(["logit_A"] + feats_b, map(float, sc.mean_))),
              "scaler_scale": dict(zip(["logit_A"] + feats_b, map(float, sc.scale_))),
              "coef_standardized": dict(zip(["logit_A"] + feats_b, map(float, lr.coef_[0]))),
              "intercept": float(lr.intercept_[0]), "C": 1.0, "penalty": "l2", "sklearn_solver": "lbfgs"}
    (a.out / "frozen_model.json").write_text(json.dumps(frozen, indent=1))
    (a.out / "summary.json").write_text(json.dumps(res, indent=1, default=float))
    print(json.dumps({k: res[k] for k in ("events", "base_rate", "chosen")}, default=float))
    print("A in-sample AUC", res["A_in_sample"]["auc"], "B oof", res["B_out_of_fold"]["auc"])


if __name__ == "__main__":
    main()
