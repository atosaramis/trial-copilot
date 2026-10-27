"""Day 1 check: run the extractor on the 5 demo protocols and compare with the registry.

Only Jan 2017 registry fields are compared (phase, planned enrollment, arms, allocation,
masking, ages, sponsor class, sites, countries). Later outcomes are never read here.

python scripts/day1_eval.py --pdf-dir DIR --cohort cohort_1436.csv \
    --registry2017 cohort_1436_registry_2017.csv.gz --runs-dir DIR [--reuse]
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.extract import extract  # noqa: E402

DEMOS = ["NCT02720510", "NCT01857271", "NCT02735980", "NCT02155660", "NCT02760602"]
KEEP_COHORT = ["nct_id", "phase", "enroll_anticipated_2017", "n_sites_2017", "lead_sponsor_class"]
KEEP_REG = ["nct_id", "n_arms", "allocation", "masking", "minimum_age", "maximum_age", "n_countries"]


def _rows(path, keep):
    csv.field_size_limit(10**9)
    op = gzip.open if str(path).endswith(".gz") else open
    with op(path, "rt") as f:
        return {r["nct_id"]: {k: r[k] for k in keep} for r in csv.DictReader(f) if r["nct_id"] in DEMOS}


def _age(s):
    m = re.match(r"(\d+)\s*Year", s or "")
    return int(m.group(1)) if m else None


def _masking_level(card_val):
    return {"None (Open Label)": "open", "Single": "single"}.get(card_val, "double+" if card_val else None)


def compare(card, coh, reg):
    reg_mask = {"Open Label": "open", "Single Blind": "single", "Double Blind": "double+"}.get(reg["masking"])
    reg_alloc = reg["allocation"] or "Single group"
    pairs = {
        "phase": (card["phase"], coh["phase"]),
        "planned_enrollment": (card["planned_enrollment"], int(float(coh["enroll_anticipated_2017"]))),
        "n_arms": (card["n_arms"], int(reg["n_arms"]) if reg["n_arms"] else None),
        "allocation": (card["allocation"], reg_alloc),
        "masking": (_masking_level(card["masking"]), reg_mask),
        "min_age_years": (card["min_age_years"], _age(reg["minimum_age"])),
        "max_age_years": (card["max_age_years"], _age(reg["maximum_age"])),
        "sponsor_type": (card["sponsor_type"], coh["lead_sponsor_class"]),
        "planned_sites": (card["planned_sites"], int(coh["n_sites_2017"])),
        "planned_countries": (card["planned_countries"], int(reg["n_countries"]) if reg["n_countries"] else None),
    }
    out = {}
    for k, (a, b) in pairs.items():
        if k == "sponsor_type":
            ok = (a == "Industry") == (b == "Industry") if a else None
        elif a is None or b is None:
            ok = None
        else:
            ok = a == b
        out[k] = {"card": a, "registry_2017": b, "match": ok}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf-dir", required=True)
    ap.add_argument("--cohort", required=True)
    ap.add_argument("--registry2017", required=True)
    ap.add_argument("--runs-dir", required=True)
    ap.add_argument("--reuse", action="store_true")
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    coh = _rows(a.cohort, KEEP_COHORT)
    reg = _rows(a.registry2017, KEEP_REG)
    summary = []
    for nct in a.only or DEMOS:
        res = extract(Path(a.pdf_dir) / f"{nct}.pdf", a.runs_dir, reuse=a.reuse)
        Path(a.runs_dir, f"{nct}.card.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
        card = res["card"]
        core = [f for f in card if f not in ("visit_count_basis", "visits_open_ended")]
        filled = sum(1 for f in core if card[f] not in (None, []))
        cited = sum(1 for f in core if card[f] not in (None, []) and f in res["_pages"])
        row = {"nct_id": nct, "fields_filled": filled, "fields_total": len(core),
               "fields_cited": cited, "schedule": res["source"]["schedule"],
               "change_history_removed": res["source"]["change_history_removed"],
               "vision": {f: card[f] for f in ["scheduled_visits_total", "visits_first_12_weeks",
                                               "visits_open_ended", "mandatory_fresh_biopsy",
                                               "inpatient_stay_required", "schedule_of_assessments_pages"]},
               "field_source": res["_field_source"], "flags": res["flags"],
               "visit_crosscheck": res["visit_crosscheck"],
               "runs": [{k: r.get(k) for k in ("step", "latency_s", "usage", "cost_usd", "reused_saved_response")}
                        for r in res["runs"]],
               "totals": res["totals"], "registry": compare(card, coh[nct], reg[nct])}
        summary.append(row)
        m = row["registry"]
        n_ok = sum(1 for v in m.values() if v["match"])
        n_chk = sum(1 for v in m.values() if v["match"] is not None)
        print(f"{nct}: filled {filled}/{len(core)}, cited {cited}, schedule {res['source']['schedule']['selected']}, "
              f"registry {n_ok}/{n_chk}, {res['totals']}", flush=True)
    Path(a.runs_dir, "day1_summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
