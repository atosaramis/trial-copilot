"""The backtest estimate makes no API call and orders its scenarios low <= expected <= high."""
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import validation_estimate as ve  # noqa: E402


def _fixture(tmp_path):
    idx = tmp_path / "index.csv"
    with idx.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["nct_id", "pdf_ok", "txt_ok", "pdf_bytes", "pages", "txt_chars", "sha256", "error"])
        for i in range(ve.TUNING + ve.HELD_OUT):
            pages = 4 if i < 3 else (50 if i < 10 else 60)
            chars = 0 if i < 10 else 200_000 + i
            w.writerow([f"NCT{i:08d}", 1, 1, 1, pages, chars, "x", ""])
    runs = tmp_path / "runs"
    for i, (tin, sin) in enumerate([(40_000, 15_000), (60_000, 20_000)]):
        d = runs / f"NCT{100 + i:08d}-abc"
        d.mkdir(parents=True)
        (d / "text.raw.jsonl").write_text(json.dumps({"usage": None}) + "\n" +
                                          json.dumps({"usage": {"prompt_tokens": tin, "completion_tokens": 1200}}))
        (d / "schedule.raw.jsonl").write_text(json.dumps({"usage": {"prompt_tokens": sin, "completion_tokens": 2800}}))
    summ = tmp_path / "summary.json"
    summ.write_text(json.dumps([{"effort": "minimal", "steps": s, "usage": {"prompt_tokens": p, "completion_tokens": 600}}
                                for s, p in [(2, 11_000), (5, 35_000)]]))
    chars = {r["nct_id"]: int(r["txt_chars"]) for r in csv.DictReader(idx.open())}
    return ve.estimate(idx, runs, summ, chars)


def test_estimate_counts_cohort_and_orders_scenarios(tmp_path):
    res = _fixture(tmp_path)
    c = res["cohort"]
    assert c["trials"] == 1436 and c["stubs_skipped"] == 3 and c["scans_read_by_vision"] == 7
    lo, ex, hi = (res["scenarios"][k] for k in ("low", "expected", "high"))
    for key in ("total_usd", "input_tokens_m", "requests", "hours_at_30_rpm"):
        assert lo[key] <= ex[key] <= hi[key], key
    assert lo["searches"] < ex["searches"]  # low case: comparable-rate feature dropped, no held-out search
    assert ex["same_at_standard_rate_usd"] > 10 * ex["total_usd"]


def test_estimator_never_imports_an_api_client():
    src = (ROOT / "scripts" / "validation_estimate.py").read_text()
    assert "openai" not in src and "META_API_KEY" not in src
