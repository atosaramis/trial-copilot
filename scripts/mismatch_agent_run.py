"""Run the Muse mismatch investigation agent over a list of trials, under a hard spend cap.

  python -m scripts.mismatch_agent_run --ids IDS.json --cards DIR --registry REG.parquet --text DIR \
      --aact DIR --out DIR --ledger LEDGER.jsonl --cap 5 --model muse-spark-1.3 [--workers 1]

--cards holds either <nct>.card.json or <nct>/extract/*/card.json (extraction output with "card"
and "_pages"); a sibling <nct>/result.json card takes precedence, matching scripts/mismatch_scan.py. --aact holds 20170105/, 20200101/ and 20230102/. Writes one JSON per trial and a
summary to --out (outside the repo). Needs META_API_KEY in the environment; never prints it.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
from pathlib import Path

import pandas as pd

from app.mismatch.agent import AgentError, TrialTools, agreement, investigate
from app.mismatch.autograde import grade, load_snapshot
from app.mismatch.finder import find_mismatches, load_pages
from app.mismatch.ledger import BudgetExceeded, SpendLedger

SNAPS = (("20170105", "2017"), ("20200101", "2020"), ("20230102", "2023"))
REG_KEYS = ["phase", "allocation", "n_arms", "enrollment", "enrollment_type", "n_sites_2017", "n_countries"]
BASE_URL = "https://api.meta.ai/v1"


def load_card(cards: Path, n: str):
    p = cards / f"{n}.card.json"
    if not p.exists():
        hits = sorted((cards / n / "extract").glob("*/card.json")) if (cards / n / "extract").exists() else []
        p = hits[0] if hits else None
    if p is None:
        return None, None
    d = json.loads(p.read_text())
    res = cards / n / "result.json"          # tuning runs: final card lives in result.json
    card = json.loads(res.read_text()).get("card") if res.exists() else None
    return card or d.get("card"), d.get("_pages")


def main():
    ap = argparse.ArgumentParser()
    for a in ("ids", "cards", "registry", "text", "aact", "out", "ledger", "model"):
        ap.add_argument(f"--{a}", required=True)
    ap.add_argument("--cap", type=float, required=True)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--effort", default="minimal")
    ap.add_argument("--tag", default="")
    ap.add_argument("--fields", default="", help="comma list of fields to investigate (default: all)")
    a = ap.parse_args()
    ids = json.loads(Path(a.ids).read_text())
    ids = ids["ids"] if isinstance(ids, dict) else ids
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    reg = pd.read_parquet(a.registry, columns=["nct_id", *REG_KEYS]).set_index("nct_id")
    snaps = {tag: load_snapshot(Path(a.aact) / sub, f"{tag}", ids) for sub, tag in SNAPS}
    ledger = SpendLedger(a.ledger, a.cap)
    from openai import OpenAI
    key = os.environ.get("META_API_KEY")
    if not key:
        raise SystemExit("META_API_KEY is not set")
    client = OpenAI(base_url=BASE_URL, api_key=key, timeout=180, max_retries=0)
    fields = set(filter(None, a.fields.split(",")))

    def one(n):
        dest = out / f"{n}.json"
        if dest.exists():
            return json.loads(dest.read_text())
        card, card_pages = load_card(Path(a.cards), n)
        if not card:
            return {"nct_id": n, "status": "no card"}
        r = {k: (None if pd.isna(v) else v) for k, v in reg.loc[n].items()}
        txt = Path(a.text) / f"{n}.txt"
        pages = load_pages(txt) if txt.exists() else []
        res = find_mismatches(n, card, r, pages)
        mms = [m for m in res.mismatches if not fields or m.field in fields]
        if not mms:
            rec = {"nct_id": n, "status": "no mismatch", "cost_usd": 0.0, "findings": []}
            dest.write_text(json.dumps(rec, indent=1))
            return rec
        sn = {t: snaps[t][n] for t in snaps if n in snaps[t]}
        tools = TrialTools(pages, sn)
        later = [s for t, s in sn.items() if t != "2017"]
        last_err = None
        for attempt in (1, 2):           # retry once at most
            try:
                rec = investigate(n, mms, tools, ledger, client, a.model, a.effort, card_pages,
                                  raw_path=out / f"{n}.attempt{attempt}.raw.jsonl", run_tag=a.tag)
                break
            except BudgetExceeded as e:
                return {"nct_id": n, "status": "budget", "error": str(e)}
            except AgentError as e:
                last_err = str(e)
        else:
            rec = {"nct_id": n, "status": "failed", "error": last_err, "findings": []}
            dest.with_suffix(".failed.json").write_text(json.dumps(rec, indent=1))
            return rec
        rec["status"] = "ok"
        rec["attempts"] = attempt
        by = {m.field: m for m in mms}
        for f in rec["findings"]:
            g = grade(by[f["field"]], later)
            f["auto_category"], f["auto_reason"] = g.category, g.reason
            f["agrees_with_auto"] = agreement(f["verdict"], g.category)
        dest.write_text(json.dumps(rec, indent=1, default=str))
        return rec

    def safe(n):
        try:
            return one(n)
        except BudgetExceeded as e:
            return {"nct_id": n, "status": "budget", "error": str(e)}
        except Exception as e:                       # one bad trial must not stop the batch
            return {"nct_id": n, "status": "failed", "error": f"{type(e).__name__}: {e}"[:300]}

    results = []
    with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
        for rec in ex.map(safe, ids):
            results.append(rec)
            fs = rec.get("findings") or []
            print(rec["nct_id"], rec.get("status"), f"${rec.get('cost_usd', 0):.4f}",
                  [(f["field"], f["verdict"], f.get("auto_category")) for f in fs], f"ledger ${ledger.spent():.4f}", flush=True)
    (out / "run_summary.json").write_text(json.dumps(
        [{k: r.get(k) for k in ("nct_id", "status", "cost_usd", "attempts", "error")} for r in results], indent=1))
    print("ledger total", ledger.spent())


if __name__ == "__main__":
    main()
