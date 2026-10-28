"""Re-write the demo memos with the registry-based risk as the headline number (Day 4 reframe).

Adds `registry_risk` (app/registry_risk.py: the locked registry model, recalibrated, Jan 2017 record
only, $0) to each saved demo audit, then has Muse Wonder rewrite the memo from the saved card, search
and risk numbers. The search is not re-run. Stops before the next call once --budget is spent.

Usage: python scripts/registry_risk_memos.py --pools DIR --out DIR [--budget 0.60] [--only NCT ...]
       [--dry-run]   (build and print the evidence packs, no call)
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import registry_risk  # noqa: E402
from app.memo import MemoError, build_evidence, check_line, write_memo  # noqa: E402
from app.tools import RegistryTools  # noqa: E402

KEEP = ("memo", "check", "model", "reasoning_effort", "usage", "cost_usd", "latency_s")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pools", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--budget", type=float, default=0.60)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    tools = RegistryTools(a.pools)
    spent, rows = 0.0, []
    for f in sorted((ROOT / "demo_cache").glob("NCT*.json")):
        d = json.loads(f.read_text())
        nct = d["nct_id"]
        if a.only and nct not in a.only:
            continue
        d["audit"]["registry_risk"] = registry_risk.assess(tools.registry_2017(nct, include_criteria=True))
        cw = d["card"]
        if a.dry_run:
            ev = build_evidence(cw["card"], d["audit"], a.pools, nct, cw.get("_pages"), cw.get("flags"))
            print(f"=== {nct}\n" + "\n".join(ev["text"].splitlines()[:4]) + "\n")
            continue
        if spent >= a.budget:
            print(f"budget reached (${spent:.4f}); stopping before {nct}")
            break
        try:
            r = write_memo(cw["card"], d["audit"], a.pools, nct, cw.get("_pages"), cw.get("flags"),
                           raw_path=out / f"{nct}.raw.json")
        except MemoError as e:
            print(f"{nct}: ERROR {e}")
            rows.append({"nct_id": nct, "error": str(e)})
            break
        spent += r["cost_usd"]
        (out / f"{nct}.memo.md").write_text(r["markdown"] + "\n")
        d["memo"] = {k: r[k] for k in KEEP}
        f.write_text(json.dumps(d, indent=1))
        rows.append({"nct_id": nct, "cost_usd": r["cost_usd"], "latency_s": r["latency_s"],
                     "headline": r["memo"]["headline"], "check_line": check_line(r["check"]),
                     "passed": r["check"]["passed"]})
        print(f"{nct}: {r['latency_s']}s ${r['cost_usd']:.4f} | {rows[-1]['check_line']}\n  {r['memo']['headline']}",
              flush=True)
    if not a.dry_run:
        (out / "summary.json").write_text(json.dumps({"total_cost_usd": round(spent, 6), "runs": rows}, indent=1))
        print(f"total ${spent:.4f}")


if __name__ == "__main__":
    main()
