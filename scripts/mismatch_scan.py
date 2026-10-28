"""Run the mismatch finder and auto-grader over a list of trials ($0, no model calls).

All inputs are passed explicitly; nothing here knows about study outcomes, and the later snapshots
are read for design fields only. Results are written outside the repo.

  python -m scripts.mismatch_scan --ids IDS.json --cards DIR --registry REG.parquet \
      --text DIR --aact DIR --out DIR

IDS.json: {"ids": [...]} or a JSON list. DIR for --cards holds <nct>/result.json with a "card".
--text holds <nct>.txt (pdftotext, one form feed per page). --aact holds 20200101/ and 20230102/.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from app.mismatch.autograde import CATEGORIES, grade, load_snapshot
from app.mismatch.finder import find_mismatches, load_pages

SNAPSHOTS = (("20200101", "2020-01-01"), ("20230102", "2023-01-02"))
REG_KEYS = ["phase", "allocation", "n_arms", "enrollment", "enrollment_type", "n_sites_2017", "n_countries"]


def run(ids, cards_dir: Path, registry: Path, text_dir: Path, aact: Path):
    reg = pd.read_parquet(registry, columns=["nct_id", *REG_KEYS]).set_index("nct_id")
    snaps = {d: load_snapshot(aact / sub, d, ids) for sub, d in SNAPSHOTS}
    rows, cleared, compared, n_cards = [], [], collections.Counter(), 0
    for n in ids:
        rj = cards_dir / n / "result.json"
        card = json.loads(rj.read_text()).get("card") if rj.exists() else None
        if not card or n not in reg.index:
            continue
        n_cards += 1
        txt = text_dir / f"{n}.txt"
        pages = load_pages(txt) if txt.exists() else None
        r = {k: (None if pd.isna(v) else v) for k, v in reg.loc[n].items()}
        res = find_mismatches(n, card, r, pages)
        compared.update(res.compared)
        cleared += [asdict(m) for m in res.cleared]
        later = [snaps[d][n] for d in snaps if n in snaps[d]]
        for m in res.mismatches:
            g = grade(m, later)
            rows.append({**{k: v for k, v in asdict(m).items() if k != "evidence"},
                         "traps": ";".join(m.traps), "page": m.evidence.page, "quote": m.evidence.quote,
                         "evidence_kind": m.evidence.kind, "category": g.category, "settled": g.settled,
                         "reason": g.reason, "later": "; ".join(f"{d}: {v:g}" if isinstance(v, float) else f"{d}: {v}"
                                                               for d, v in g.later)})
    return rows, cleared, compared, n_cards


def summarize(rows, cleared, compared, n_cards) -> dict:
    by_field = collections.defaultdict(collections.Counter)
    for r in rows:
        by_field[r["field"]][r["category"]] += 1
    cat = collections.Counter(r["category"] for r in rows)
    amb = collections.Counter(r["reason"].split(";")[0].split(" (")[0].split(" actual")[0] for r in rows
                              if r["category"] == "ambiguous")
    return {"trials_with_cards": n_cards, "fields_compared": dict(compared), "mismatches": len(rows),
            "trials_with_mismatch": len({r["nct_id"] for r in rows}),
            "cleared_by_trap": len(cleared),
            "severity": dict(collections.Counter(r["severity"] for r in rows)),
            "categories": {c: cat.get(c, 0) for c in CATEGORIES},
            "settled": sum(r["settled"] for r in rows), "ambiguous": cat.get("ambiguous", 0),
            "ambiguous_reasons": dict(amb),
            "traps": dict(collections.Counter(t for r in rows for t in r["traps"].split(";") if t)),
            "by_field": {f: {c: c_.get(c, 0) for c in CATEGORIES} for f, c_ in sorted(by_field.items())}}


def main():
    ap = argparse.ArgumentParser()
    for a in ("ids", "cards", "registry", "text", "aact", "out"):
        ap.add_argument(f"--{a}", required=True)
    a = ap.parse_args()
    ids = json.loads(Path(a.ids).read_text())
    ids = ids["ids"] if isinstance(ids, dict) else ids
    rows, cleared, compared, n = run(ids, Path(a.cards), Path(a.registry), Path(a.text), Path(a.aact))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "mismatches.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    (out / "cleared.json").write_text(json.dumps(cleared, indent=1, default=str))
    s = summarize(rows, cleared, compared, n)
    (out / "summary.json").write_text(json.dumps(s, indent=1))
    print(json.dumps(s, indent=1))


if __name__ == "__main__":
    main()
