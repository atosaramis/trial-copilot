"""Build demo_cache/ for the 5 demo trials from saved run outputs (no model calls).

Each demo file holds derived results only: the trial card (fields, page citations, flags), the
search trace (no raw model turns), the risk numbers and the checked memo. It never holds
protocol text beyond the short quotes on the card. The Jan 2020 registry outcome goes in a
separate file, `demo_cache/reveal.json`, which only the reveal button reads; no model step
reads it.

Usage: python scripts/build_demo_cache.py --cards DIR --audits DIR --memos DIR [--memos DIR ...]
       --cohort PATH --index PATH
"""
import argparse
import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMOS = ["NCT02720510", "NCT01857271", "NCT02735980", "NCT02155660", "NCT02760602"]  # lead demo first
LABELS = {"NCT02720510": "Multiple myeloma, Phase 2 (Novartis)",
          "NCT01857271": "EGFR-mutant stage III lung cancer, Phase 2 (academic)",
          "NCT02735980": "Small-cell lung cancer, Phase 2 (Lilly)",
          "NCT02155660": "COPD with exacerbations, Phase 3 (AstraZeneca)",
          "NCT02760602": "Prodromal Alzheimer's disease, Phase 3 (Lilly)"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cards", required=True)
    ap.add_argument("--audits", required=True)
    ap.add_argument("--memos", required=True, action="append", help="later folders win")
    ap.add_argument("--cohort", required=True)
    ap.add_argument("--index", required=True)
    a = ap.parse_args()
    cohort = {r["nct_id"]: r for r in csv.DictReader(open(a.cohort))}
    index = {r["nct_id"]: r for r in csv.DictReader(open(a.index))}
    out = ROOT / "demo_cache"
    out.mkdir(exist_ok=True)
    reveal = {}
    for nct in DEMOS:
        c = json.loads((Path(a.cards) / f"{nct}.card.json").read_text())
        audit = json.loads((Path(a.audits) / f"{nct}.minimal.r1.json").read_text())
        audit["search"].pop("turns", None)  # raw model turns stay out; the steps carry the trace
        memo = None
        for d in a.memos:
            p = Path(d) / f"{nct}.memo.json"
            if p.exists():
                memo = json.loads(p.read_text())
        memo = {k: memo[k] for k in ("memo", "check", "model", "reasoning_effort", "usage", "cost_usd",
                                     "latency_s")}
        row = cohort[nct]
        demo = {"nct_id": nct, "label": LABELS[nct], "registry_title_2017": row["title"],
                "pdf_sha256": index[nct]["sha256"], "pdf_pages": int(index[nct]["pages"]),
                "protocol_url": row["protocol_doc_url"],
                "card": {"card": c["card"], "_pages": c["_pages"], "flags": c.get("flags", [])},
                "audit": audit, "memo": memo}
        (out / f"{nct}.json").write_text(json.dumps(demo, indent=1, ensure_ascii=False))
        reveal[nct] = {"registry_status": row["status_2020"], "why_stopped": re.sub(r"~\s+", " ", row["why_stopped"]) or None,
                       "as_of": "Jan 1, 2020 ClinicalTrials.gov snapshot (AACT)",
                       "label": "registry-reported"}
    (out / "reveal.json").write_text(json.dumps(reveal, indent=1, ensure_ascii=False))
    print("wrote", len(DEMOS), "demos")


if __name__ == "__main__":
    main()
