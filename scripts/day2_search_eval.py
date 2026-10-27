"""Day 2 check: run the step-by-step search and the risk maths on demo trial cards.

python scripts/day2_search_eval.py --cards-dir DIR --pools-dir DIR --out DIR \
    [--only NCT...] [--efforts minimal low] [--repeats 2] [--model muse-spark-1.3-contributor]

Quality is scored by code, with anchors fixed before any search ran (ANCHORS below): the share
of the chosen comparable set whose conditions or title name the trial's disease, the set size,
and run-to-run overlap. No Jan 2020 outcome is read anywhere in this script.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.agent import SearchError  # noqa: E402
from app.audit import search_and_risk  # noqa: E402

# Disease anchors per demo trial, written before the first search run (Oct 27 evening).
ANCHORS = {
    "NCT02720510": r"myeloma",
    "NCT01857271": r"non[- ]?small[- ]cell|nsclc",
    "NCT02735980": r"(?<!non-)(?<!non )(?<!non)small[- ]cell (lung|carcinoma|cancer)|\bsclc\b",
    "NCT02155660": r"copd|chronic obstructive|pulmonary disease, chronic obstructive",
    "NCT02760602": r"alzheimer",
}
SIZE_OK = (30, 500)


def quality(nct: str, out: dict, rows_by_id: dict) -> dict:
    ids = (out.get("comparable") or {}).get("nct_ids") or []
    rx = re.compile(ANCHORS[nct], re.I)
    rel = sum(1 for i in ids if rx.search(rows_by_id.get(i, ""))) / len(ids) if ids else 0.0
    size_ok = SIZE_OK[0] <= len(ids) <= SIZE_OK[1]
    errors = sum(1 for s in out["search"]["steps"] if s.get("status") != "ok")
    return {"n_comparable": len(ids), "relevance": round(rel, 3), "size_ok": size_ok,
            "tool_errors": errors, "steps": out["search"]["tool_calls_used"],
            "capped": out["search"]["capped"],
            "score": round(rel * (1.0 if size_ok else 0.5), 3)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cards-dir", required=True)
    ap.add_argument("--pools-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--efforts", nargs="*", default=["minimal"])
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--model", default="muse-spark-1.3")
    a = ap.parse_args()
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    from app.tools import RegistryTools
    t = RegistryTools(a.pools_dir)
    rows_by_id = {r[0]: f"{r[1] or ''} | {r[2] or ''} | {r[3] or ''}" for r in t.con.execute(
        "SELECT nct_id, conditions, mesh_conditions, title FROM similar_pool").fetchall()}
    summary = []
    for nct in a.only or list(ANCHORS):
        card = json.loads(Path(a.cards_dir, f"{nct}.card.json").read_text())["card"]
        for eff in a.efforts:
            for rep in range(1, a.repeats + 1):
                tag = f"{nct}.{eff}.r{rep}"
                if (out_dir / f"{tag}.json").exists():
                    res = json.loads((out_dir / f"{tag}.json").read_text())
                else:
                    try:
                        res = search_and_risk(card, nct, a.pools_dir, model=a.model, reasoning_effort=eff,
                                              raw_path=out_dir / f"{tag}.raw.jsonl")
                    except SearchError as e:
                        print(f"{tag}: Muse error {e}", flush=True)
                        (out_dir / f"{tag}.error.txt").write_text(str(e))
                        raise
                    res["quality"] = quality(nct, res, rows_by_id)
                    (out_dir / f"{tag}.json").write_text(json.dumps(res, indent=1, default=str, ensure_ascii=False))
                q, s, r = res["quality"], res["search"], res["risk"]
                cb = r["comparable_trials"] or {}
                sp = r["site_pace"]
                row = {"tag": tag, "nct_id": nct, "effort": eff, "rep": rep, **q,
                       "cost_usd": s["cost_usd"], "latency_s": s["latency_s"], "usage": s["usage"],
                       "events": cb.get("events"), "rate": cb.get("rate"), "ci95": cb.get("ci95"),
                       "pace": sp["patients_per_site_per_month"],
                       "share_faster": sp["share_of_completed_comparables_at_least_this_fast"],
                       "competing": (r["competing_trials"] or {}).get("n_recruiting_jan_2017"),
                       "flags": s["flags"]}
                summary.append(row)
                print(json.dumps({k: row[k] for k in ("tag", "n_comparable", "relevance", "steps", "capped",
                                                      "cost_usd", "latency_s", "events", "competing")}), flush=True)
                time.sleep(0.5)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1, default=str))


if __name__ == "__main__":
    main()
