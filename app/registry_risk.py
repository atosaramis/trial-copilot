"""Registry-only risk of stopping for poor enrollment, from the trial's Jan 5, 2017 registry record.

This is the headline number. It is the locked 13-field baseline (A) recalibrated with the frozen rule
(preregistration-addendum.md). Held-out test (873 trials, 53 stops): AUC 0.66, mean predicted 6.3% vs
6.1% observed (docs/backtest-heldout.md). The protocol features and the comparable stop rate added no
detectable gain in the tuning backtest, so they and the competing counts are shown as context for
reviewer judgement only. Parity: matches the locked baseline + recalibration within 0.0001 on all 1,436
cohort trials (checked Oct 27 against lar36/data/baseline_split.pkl).
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

import pandas as pd

MODEL = json.loads((Path(__file__).parent / "data" / "registry_model.json").read_text())
ONC_RX = re.compile(r"cancer|tumou?r|carcinom|lymphom|leukemi|leukaemi|neoplas|myelom|sarcom|melanom|glioma|metasta", re.I)


def _f(v):
    try:
        x = float(v)
        return None if math.isnan(x) else x
    except (TypeError, ValueError):
        return None


def features(reg: dict) -> dict:
    """The 13 baseline fields, defined as in the Oct 13 study (lar36 scripts/10_build.py)."""
    L = pd.Timestamp(MODEL["landmark"])
    start = pd.to_datetime(reg.get("start_date"), errors="coerce")
    pc = pd.to_datetime(reg.get("primary_completion_date"), errors="coerce")
    crit = str(reg.get("criteria") or "")
    phase = str(reg.get("phase") or "")
    enroll, sites, countries = _f(reg.get("enrollment")), _f(reg.get("n_sites_2017")), _f(reg.get("n_countries"))
    x = {
        "l_enroll": None if enroll is None else math.log1p(enroll),
        "l_sites": math.log1p(sites or 0.0),
        "l_countries": math.log1p(countries or 0.0),
        "ph3": float(phase == "Phase 3"), "ph23": float(phase == "Phase 2/Phase 3"), "ph4": float(phase == "Phase 4"),
        "industry": float(str(reg.get("lead_class") or "").lower() == "industry"),
        "m_since_start": None if pd.isna(start) else min(max(round((L - start).days / 30.44, 1), -24), 240),
        "m_to_pc": None if pd.isna(pc) else min(max(round((pc - L).days / 30.44, 1), -60), 240),
        "l_elig": math.log1p(len(crit)),
        "n_criteria": float(min(max(len(re.findall(r"\n\s*(?:-|\d+\.|•|\*)", crit.replace("~", "\n"))), 0), 80)),
        "oncology": float(bool(ONC_RX.search(str(reg.get("conditions") or "")))),
        "us_site": _us_in_first8(reg.get("countries")),
    }
    return {k: (MODEL["medians"][k] if v is None else v) for k, v in x.items()}


SUFFIX_RX = re.compile(r"^(?:Republic|Islamic|The |the |Democratic|Province|Bolivarian|Plurinational|United Republic|Federated)")


def _us_in_first8(countries: str) -> float:
    """us_site as the locked baseline defined it: 'United States' among the first 8 country names in
    alphabetical order (the study kept only 8). Comma-containing names such as 'Korea, Republic of' are rejoined."""
    names: list[str] = []
    for part in [x.strip() for x in str(countries or "").split(",") if x.strip()]:
        if names and SUFFIX_RX.match(part):
            names[-1] += ", " + part
        else:
            names.append(part)
    return float("United States" in sorted(set(names))[:8])


def wilson(k: int, n: int, z: float = 1.96) -> list[float]:
    if n == 0:
        return [0.0, 1.0]
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [max(0.0, c - h), min(1.0, c + h)]


def assess(reg: dict | None) -> dict | None:
    if not reg:
        return None
    x = features(reg)
    z = MODEL["intercept"] + sum(MODEL["coef"][k] * (x[k] - MODEL["scaler_mean"][k]) / MODEL["scaler_scale"][k]
                                 for k in MODEL["features"])
    pA = min(max(1 / (1 + math.exp(-z)), 1e-6), 1 - 1e-6)
    r = MODEL["recalibration"]
    p = 1 / (1 + math.exp(-(r["a"] + r["b"] * math.log(pA / (1 - pA)))))
    out = {"risk": round(p, 4), "label": "registry-based risk, calibrated", "inputs": "Jan 5, 2017 registry record only"}
    ref = MODEL.get("heldout_reference")
    if ref:
        b = next((b for b in ref["bins"] if p <= b["max"]), ref["bins"][-1])
        out["same_fifth_heldout"] = {"range": [b["min"], b["max"]], "n": b["n"], "events": b["events"],
                                         "rate": round(b["events"] / b["n"], 4), "ci95": [round(v, 4) for v in wilson(b["events"], b["n"])]}
        out["base_rate_heldout"] = ref["base_rate"]
        out["heldout_auc"] = ref["auc"]
        out["times_base_rate"] = round(p / ref["base_rate"]["rate"], 1)
    return out
