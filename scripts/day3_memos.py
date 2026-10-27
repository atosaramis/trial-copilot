"""Day 3: write the sponsor memo for each demo trial with Muse Wonder, check it in code, save.

Usage: python scripts/day3_memos.py --cards DIR --audits DIR --pools DIR --out DIR [--effort medium]
Inputs and outputs live outside the repo. Stops before the next call once --budget is spent.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from types import SimpleNamespace  # noqa: E402

from app.memo import MemoError, check_line, write_memo  # noqa: E402


class SavedReply:
    """Re-check a saved Wonder reply without a new call (no spend)."""

    def __init__(self, path):
        self.d = json.loads(Path(path).read_text())["response"]
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **_):
        msg = SimpleNamespace(content=self.d["choices"][0]["message"]["content"])
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)], model_dump=lambda: self.d)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cards", required=True)
    ap.add_argument("--audits", required=True)
    ap.add_argument("--pools", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--effort", default="medium")
    ap.add_argument("--budget", type=float, default=3.0)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--reuse", action="store_true", help="re-check saved replies instead of calling")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    spent, rows = 0.0, []
    for cf in sorted(Path(a.cards).glob("*.card.json")):
        nct = cf.name.split(".")[0]
        if a.only and nct not in a.only:
            continue
        if spent >= a.budget:
            print(f"budget reached (${spent:.4f}); stopping before {nct}")
            break
        c = json.loads(cf.read_text())
        audit = json.loads((Path(a.audits) / f"{nct}.minimal.r1.json").read_text())
        raw = out / f"{nct}.raw.json"
        if a.reuse and not raw.exists():
            sys.exit(f"--reuse given but {raw} is missing; refusing to make a paid call")
        reused = a.reuse
        try:
            r = write_memo(c["card"], audit, a.pools, nct, c.get("_pages"), c.get("flags"),
                           reasoning_effort=a.effort, client=SavedReply(raw) if reused else None,
                           raw_path=None if reused else raw)
        except MemoError as e:
            print(f"{nct}: ERROR {e}")
            rows.append({"nct_id": nct, "error": str(e)})
            break
        if reused:  # latency of the original call is not stored in the reply; keep the first measurement
            r["latency_s"] = json.loads(raw.read_text()).get("latency_s")
        r["reused_saved_reply"] = reused
        spent += 0 if reused else r["cost_usd"]
        (out / f"{nct}.memo.md").write_text(r["markdown"] + "\n")
        (out / f"{nct}.memo.json").write_text(json.dumps({k: v for k, v in r.items() if k != "markdown"}, indent=1))
        u = r["usage"]
        row = {"nct_id": nct, "latency_s": r["latency_s"], "cost_usd": r["cost_usd"],
               "prompt_tokens": u.get("prompt_tokens"), "completion_tokens": u.get("completion_tokens"),
               "reasoning_tokens": (u.get("completion_tokens_details") or {}).get("reasoning_tokens"),
               "reused_saved_reply": reused, "check": r["check"], "check_line": check_line(r["check"])}
        rows.append(row)
        print(f"{nct}: {r['latency_s']}s ${r['cost_usd']:.4f} | {row['check_line']}", flush=True)
    (out / "summary.json").write_text(json.dumps({"total_cost_usd": round(spent, 6), "runs": rows}, indent=1))
    print(f"total ${spent:.4f}")


if __name__ == "__main__":
    main()
