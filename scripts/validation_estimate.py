"""Cost and time estimate for the pre-registered backtest (extraction + search on the 1,436-trial cohort).

Makes no API call. Reads per-trial page and character counts from the protocol index (kept outside the repo)
and the token counts measured on the Oct 27 demo runs, then prices them at the contributor rate.
The memo is excluded: the backtest scores trials from the trial card and the search, not from the memo.

    python scripts/validation_estimate.py --index ../prep/protocols/index.csv \
        --extract-runs ../day2-runs/extract-I --search-summary ../day2-runs/search-compare/summary.json
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import math
import statistics as st
from pathlib import Path

PRICE_IN, PRICE_OUT = 0.10, 0.20        # USD per 1M tokens, muse-spark-1.3-contributor
STD_IN, STD_OUT = 1.25, 4.25            # standard rate, for comparison only
TUNING, HELD_OUT = 563, 873             # preregistration.md
CONTEXT = 1_048_576
RPM_RUNNER, RPM_LIMIT, TPM_LIMIT = 30, 150, 3_000_000   # runner setting; contributor limits per team
LOW_TEXT_CHARS_PER_PAGE = 300
SCAN_MAX_PAGES = 10


def last_usage(path: Path) -> dict | None:
    u = None
    for line in path.read_text().splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        u = rec.get("usage") or u
    return u


def measured_extraction(run_dir: Path) -> list[dict]:
    rows = []
    for d in sorted(glob.glob(str(run_dir / "NCT*-*"))):
        d = Path(d)
        t, s = last_usage(d / "text.raw.jsonl"), last_usage(d / "schedule.raw.jsonl")
        if t and s:
            rows.append({"run": d.name, "text_in": t["prompt_tokens"], "text_out": t["completion_tokens"],
                         "sched_in": s["prompt_tokens"], "sched_out": s["completion_tokens"]})
    return rows


def cost(tin: float, tout: float, pin=PRICE_IN, pout=PRICE_OUT) -> float:
    return tin / 1e6 * pin + tout / 1e6 * pout


def estimate(index: Path, extract_runs: Path, search_summary: Path, chars_by_nct: dict[str, int]) -> dict:
    trials = list(csv.DictReader(index.open()))
    meas = measured_extraction(extract_runs)
    srch = json.loads(search_summary.read_text())
    if len(trials) != TUNING + HELD_OUT:
        raise SystemExit(f"index has {len(trials)} trials, expected {TUNING + HELD_OUT}")

    # chars per text-call input token, from the measured runs (prompt overhead included)
    ratios = [chars_by_nct[m["run"].split("-")[0]] / m["text_in"] for m in meas]
    text_out = [m["text_out"] for m in meas]
    sched_in = [m["sched_in"] for m in meas]
    sched_out = [m["sched_out"] for m in meas]
    s_in = [x["usage"]["prompt_tokens"] for x in srch if x["effort"] == "minimal"]
    s_out = [x["usage"]["completion_tokens"] for x in srch if x["effort"] == "minimal"]
    s_steps = [x["steps"] for x in srch if x["effort"] == "minimal"]

    text_trials, scans, stubs = [], 0, 0
    for r in trials:
        pages, chars = int(r["pages"] or 0), int(r["txt_chars"] or 0)
        if pages and chars / pages >= LOW_TEXT_CHARS_PER_PAGE:
            text_trials.append(chars)
        elif pages >= SCAN_MAX_PAGES:
            scans += 1
        else:
            stubs += 1
    total_chars = sum(text_trials)

    scen = {
        # chars/token, retry overhead, schedule in/out, text out, scan in/out per page, search in/out, held-out search?
        "low": dict(cpt=max(ratios), retry=0.00, s_in=min(sched_in), s_out=min(sched_out), t_out=min(text_out),
                    scan_in=2_000, scan_out=1_500, q_in=min(s_in), q_out=min(s_out), held_search=False,
                    steps=min(s_steps)),
        "expected": dict(cpt=sum(chars_by_nct[m["run"].split("-")[0]] for m in meas) / sum(m["text_in"] for m in meas),
                         retry=0.05, s_in=st.mean(sched_in), s_out=st.mean(sched_out), t_out=st.mean(text_out),
                         scan_in=2_500, scan_out=2_500, q_in=st.mean(s_in), q_out=st.mean(s_out), held_search=True,
                         steps=st.mean(s_steps)),
        "high": dict(cpt=min(ratios), retry=0.15, s_in=max(sched_in) * 1.25, s_out=max(sched_out), t_out=max(text_out),
                     scan_in=4_000, scan_out=3_500, q_in=max(s_in) * 1.5, q_out=max(s_out) * 1.5, held_search=True,
                     steps=6),
    }
    out = {"cohort": {"trials": len(trials), "tuning": TUNING, "held_out": HELD_OUT,
                      "text_protocols": len(text_trials), "scans_read_by_vision": scans, "stubs_skipped": stubs,
                      "text_chars_total": total_chars,
                      "pages_median": st.median(int(r["pages"] or 0) for r in trials),
                      "over_context_at_high": sum(1 for c in text_trials if c / min(ratios) > CONTEXT)},
           "measured": {"extraction_runs": len(meas), "chars_per_token": [round(x, 2) for x in ratios],
                        "schedule_in": sched_in, "schedule_out": sched_out, "text_out": text_out,
                        "search_runs": len(s_in), "search_in": s_in, "search_out": s_out, "search_steps": s_steps},
           "scenarios": {}}
    for name, p in scen.items():
        n_text = len(text_trials)
        ext_in = total_chars / p["cpt"] + n_text * p["s_in"] + scans * SCAN_MAX_PAGES * p["scan_in"]
        ext_out = n_text * (p["t_out"] + p["s_out"]) + scans * p["scan_out"]
        n_search = TUNING + (HELD_OUT if p["held_search"] else 0)
        n_search_eff = round(n_search * (n_text + scans) / len(trials))  # stubs get no search
        q_in, q_out = n_search_eff * p["q_in"], n_search_eff * p["q_out"]
        k = 1 + p["retry"]
        ext_in, ext_out, q_in, q_out = ext_in * k, ext_out * k, q_in * k, q_out * k
        reqs = ((n_text * 2 + scans) + n_search_eff * (p["steps"] + 1)) * k
        tokens = ext_in + ext_out + q_in + q_out
        minutes_runner = reqs / RPM_RUNNER
        minutes_floor = max(reqs / RPM_LIMIT, tokens / TPM_LIMIT)
        out["scenarios"][name] = {
            "extraction_usd": round(cost(ext_in, ext_out), 2),
            "search_usd": round(cost(q_in, q_out), 2),
            "total_usd": round(cost(ext_in + q_in, ext_out + q_out), 2),
            "same_at_standard_rate_usd": round(cost(ext_in + q_in, ext_out + q_out, STD_IN, STD_OUT), 0),
            "input_tokens_m": round((ext_in + q_in) / 1e6, 1), "output_tokens_m": round((ext_out + q_out) / 1e6, 2),
            "searches": n_search_eff, "requests": math.ceil(reqs),
            "hours_at_30_rpm": round(minutes_runner / 60, 1),
            "hours_floor_at_contributor_limits": round(minutes_floor / 60, 1),
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", type=Path, required=True)
    ap.add_argument("--extract-runs", type=Path, required=True)
    ap.add_argument("--search-summary", type=Path, required=True)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    chars = {r["nct_id"]: int(r["txt_chars"] or 0) for r in csv.DictReader(a.index.open())}
    res = estimate(a.index, a.extract_runs, a.search_summary, chars)
    text = json.dumps(res, indent=1)
    if a.out:
        a.out.write_text(text)
    print(text)


if __name__ == "__main__":
    main()
