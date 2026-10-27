"""Resumable backtest runner: extraction (text + schedule images, or page images for scans) and the
agentic past-trial search, on the TUNING set only. No memo.

    python -m backtest.run --cohort ../prep/cohort_1436.csv --pdf-dir ../prep/protocols/pdf \
        --pools ../prep/pools --out ../backtest-tuning --limit 20

- Reads only `nct_id` and `split` from the cohort file: no outcome column is loaded here.
- Refuses any split other than "tuning".
- Idempotent: a trial with result.json is skipped; saved raw extraction responses are reused, so a
  crash never bills the same extraction twice. A failed trial is logged to errors.jsonl and retried
  only once, and only for a transient API error (429, 5xx, timeout, connection); every retry is logged.
- Rate limited across workers (requests and estimated tokens per minute), below the contributor limits.
- Stops launching new trials once --budget USD is spent (running trials finish).
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import threading
import time
import traceback
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from app import agent, extract
from app.audit import search_and_risk

MODEL = "muse-spark-1.3-contributor"
ORDER_SEED = 2026
RETRYABLE = ("RateLimit", " 429", " 500", " 502", " 503", " 504", "Timeout", "APIConnection", "InternalServer")


class Limiter:
    """Sliding one-minute window on requests and estimated input tokens, shared by all workers."""

    def __init__(self, rpm: int, tpm: int):
        self.rpm, self.tpm = rpm, tpm
        self.events: deque = deque()
        self.lock = threading.Lock()

    def acquire(self, tokens: int):
        while True:
            with self.lock:
                now = time.time()
                while self.events and now - self.events[0][0] > 60:
                    self.events.popleft()
                used_t = sum(t for _, t in self.events)
                if len(self.events) < self.rpm and (used_t + tokens <= self.tpm or not self.events):
                    self.events.append((now, tokens))
                    return
            time.sleep(0.5)


def estimate_tokens(messages) -> int:
    chars, images = 0, 0
    for m in messages:
        c = m.get("content") if isinstance(m, dict) else None
        if isinstance(c, str):
            chars += len(c)
        elif isinstance(c, list):
            for part in c:
                if part.get("type") == "text":
                    chars += len(part.get("text", ""))
                else:
                    images += 1
        if isinstance(m, dict) and m.get("tool_calls"):
            chars += len(json.dumps(m["tool_calls"]))
    return int(chars / 3.5) + images * 2500


class LimitedClient:
    """Wraps the OpenAI client so every chat call waits for the shared limiter."""

    def __init__(self, inner, limiter: Limiter):
        self._inner, self._limiter = inner, limiter
        self.chat = self
        self.completions = self

    def create(self, **kw):
        self._limiter.acquire(estimate_tokens(kw.get("messages", [])))
        return self._inner.chat.completions.create(**kw)


def tuning_ids(cohort: Path) -> list[str]:
    with cohort.open() as f:
        rd = csv.DictReader(f)
        ids = [r["nct_id"] for r in rd if r["split"] == "tuning"]  # only these two columns are read
    ids.sort()
    random.Random(ORDER_SEED).shuffle(ids)
    return ids


def raw_usage_cost(path: Path, model: str) -> float:
    """Cost of calls recorded in a raw file (used for failed attempts)."""
    if not path.exists():
        return 0.0
    total = 0.0
    for line in path.read_text().splitlines():
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        u = d.get("usage") or (d.get("_summary") or {}).get("usage")
        if u and "_summary" in d:
            total += extract.cost_usd(u, model)
        elif u and d.get("object") == "chat.completion":
            total += agent.cost_usd(u, model)
    return total


def features(card: dict | None, sr: dict | None) -> dict:
    card = card or {}
    risk = (sr or {}).get("risk") or {}
    comp = risk.get("comparable_trials") or {}
    sp = risk.get("site_pace") or {}
    compet = risk.get("competing_trials") or {}
    return {
        "pace": sp.get("patients_per_site_per_month"),
        "pace_sites_source": sp.get("sites_source"), "pace_months_source": sp.get("months_source"),
        "required_biomarker_text": card.get("required_biomarker"),
        "clinic_visits_days_1_85": card.get("clinic_visits_first_12_weeks"),
        "contacts_screening_to_day_85": card.get("contacts_screening_to_week_12"),
        "screening_clinic_visits": card.get("screening_clinic_visits"),
        "screening_window_days": card.get("screening_window_days"),
        "comparable_rate": comp.get("rate"), "comparable_n": comp.get("n"), "comparable_events": comp.get("events"),
        "competing_n": compet.get("n_recruiting_jan_2017"),
        "planned_enrollment": card.get("planned_enrollment"), "planned_sites": card.get("planned_sites"),
        "enrollment_period_months": card.get("enrollment_period_months"),
    }


def is_retryable(err: str) -> bool:
    return any(k in err for k in RETRYABLE)


def run_trial(nct: str, a, client, log) -> dict:
    tdir = a.out / "trials" / nct
    done = tdir / "result.json"
    if done.exists():
        return json.loads(done.read_text()) | {"skipped": True}
    tdir.mkdir(parents=True, exist_ok=True)
    pdf = a.pdf_dir / f"{nct}.pdf"
    res = {"nct_id": nct, "model": MODEL, "started": time.strftime("%Y-%m-%d %H:%M:%S"), "attempts": []}
    t0 = time.time()
    ext = None
    for attempt in (1, 2):
        try:
            ext = extract.extract(pdf, runs_dir=tdir / "extract", reuse=True, model=MODEL, client=client)
            break
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {str(e)[:600]}"
            paid = sum(raw_usage_cost(p, MODEL) for p in (tdir / "extract").glob("*/*.raw.jsonl"))
            res["attempts"].append({"stage": "extract", "attempt": attempt, "error": err})
            log({"nct_id": nct, "stage": "extract", "attempt": attempt, "error": err, "paid_so_far_usd": paid})
            if attempt == 1 and is_retryable(err):
                time.sleep(20)
                continue
            res.update(status="failed", stage="extract", error=err,
                       cost_usd=round(paid, 6), elapsed_s=round(time.time() - t0, 1))
            (tdir / "failed.json").write_text(json.dumps(res, indent=1))
            return res
    kind = ext["source"].get("kind", "text")
    res.update(kind=kind, n_pages=ext["source"]["n_pages"], text_chars_sent=ext["source"].get("text_chars_sent"),
               text_trimmed=ext["source"].get("text_trimmed"),
               extract_cost_usd=round(sum(r["cost_usd"] for r in ext.get("runs", [])
                                          if not r.get("reused_saved_response")), 6),
               extract_tokens={k: (ext.get("totals") or {}).get(k) for k in ("prompt_tokens", "completion_tokens")},
               extract_latency_s=(ext.get("totals") or {}).get("latency_s"),
               extract_reused=all(r.get("reused_saved_response") for r in ext.get("runs", [])) and bool(ext.get("runs")),
               card_flags=ext.get("flags", []))
    card = ext.get("card")
    sr = None
    search_cost = 0.0
    if card is not None:
        for attempt in (1, 2):
            raw = tdir / f"search.attempt{attempt}.raw.jsonl"
            try:
                sr = search_and_risk(card, nct_id=nct, pools_dir=a.pools, model=MODEL, client=client, raw_path=raw)
                search_cost += sr["search"]["cost_usd"]
                break
            except Exception as e:  # noqa: BLE001
                err = f"{type(e).__name__}: {str(e)[:600]}"
                paid = raw_usage_cost(raw, MODEL)
                search_cost += paid
                res["attempts"].append({"stage": "search", "attempt": attempt, "error": err, "paid_usd": paid})
                log({"nct_id": nct, "stage": "search", "attempt": attempt, "error": err, "paid_usd": paid})
                if attempt == 1 and is_retryable(err):
                    time.sleep(20)
                    continue
                res.update(search_status="failed", search_error=err)
                break
    s = (sr or {}).get("search") or {}
    res.update(status="ok" if (card is None or sr is not None) else "partial",
               search_cost_usd=round(search_cost, 6),
               search_tokens=s.get("usage"), search_latency_s=s.get("latency_s"),
               search_steps=s.get("tool_calls_used"), search_capped=s.get("capped"),
               search_requests=len(s.get("turns") or []),
               search_flags=s.get("flags"), risk_flags=((sr or {}).get("risk") or {}).get("flags"),
               comparable_args=((sr or {}).get("comparable") or {}).get("args"),
               features=features(card, sr), card=card,
               cost_usd=round(res["extract_cost_usd"] + search_cost, 6),
               elapsed_s=round(time.time() - t0, 1), finished=time.strftime("%Y-%m-%d %H:%M:%S"))
    if sr is not None:
        (tdir / "search_risk.json").write_text(json.dumps({k: v for k, v in sr.items()}, indent=1, default=str))
    target = done if res["status"] == "ok" else tdir / "failed.json"
    target.write_text(json.dumps(res, indent=1, default=str))
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cohort", type=Path, required=True)
    ap.add_argument("--pdf-dir", type=Path, required=True)
    ap.add_argument("--pools", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--split", default="tuning")
    ap.add_argument("--limit", type=int, default=None, help="process the first N trials of the fixed order")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--rpm", type=int, default=60)
    ap.add_argument("--tpm", type=int, default=1_500_000)
    ap.add_argument("--budget", type=float, default=7.0, help="stop launching trials once this much USD is spent")
    a = ap.parse_args(argv)
    if a.split != "tuning":
        raise SystemExit("This runner only processes the tuning set. The held-out set is not touched.")
    a.out.mkdir(parents=True, exist_ok=True)
    ids = tuning_ids(a.cohort)
    if len(ids) != 563:
        raise SystemExit(f"expected 563 tuning trials, found {len(ids)}")
    (a.out / "order.json").write_text(json.dumps({"seed": ORDER_SEED, "ids": ids}))
    todo = ids[: a.limit] if a.limit else ids
    lock = threading.Lock()

    def log(rec):
        with lock, open(a.out / "errors.jsonl", "a") as f:
            f.write(json.dumps(rec | {"t": time.strftime("%Y-%m-%d %H:%M:%S")}) + "\n")

    from openai import OpenAI
    import os
    inner = OpenAI(base_url=extract.BASE_URL, api_key=os.environ["META_API_KEY"], timeout=600, max_retries=0)
    client = LimitedClient(inner, Limiter(a.rpm, a.tpm))
    spent = 0.0
    ledger = a.out / "spend_ledger.jsonl"  # append-only: one line per finished trial attempt
    prior = sum(json.loads(x)["cost_usd"] for x in ledger.read_text().splitlines()) if ledger.exists() else 0.0
    print(f"{len(todo)} trials in this run; ${prior:.4f} already spent in earlier runs", flush=True)
    t_start = time.time()
    n_done = 0
    with ThreadPoolExecutor(a.workers) as pool:
        futs = {}
        it = iter(todo)
        stop = False

        def submit_next():
            nonlocal stop
            if stop:
                return
            for nct in it:
                if (a.out / "trials" / nct / "result.json").exists():
                    continue
                if prior + spent >= a.budget:
                    stop = True
                    print(f"budget ${a.budget} reached; not starting more trials", flush=True)
                    return
                futs[pool.submit(run_trial, nct, a, client, log)] = nct
                return

        for _ in range(a.workers * 2):
            submit_next()
        while futs:
            for f in as_completed(list(futs)):
                nct = futs.pop(f)
                try:
                    r = f.result()
                except Exception:  # noqa: BLE001
                    log({"nct_id": nct, "stage": "runner", "error": traceback.format_exc()[-800:]})
                    r = {"status": "crashed", "cost_usd": 0}
                with lock:
                    if not r.get("skipped"):
                        spent += r.get("cost_usd") or 0.0
                        with open(ledger, "a") as lf:
                            lf.write(json.dumps({"nct_id": nct, "status": r.get("status"),
                                                 "cost_usd": r.get("cost_usd") or 0.0,
                                                 "t": time.strftime("%Y-%m-%d %H:%M:%S")}) + "\n")
                    n_done += 1
                print(f"[{n_done}/{len(todo)}] {nct} {r.get('status')} {r.get('kind', '')} "
                      f"${r.get('cost_usd', 0):.4f} {r.get('elapsed_s', '')}s | run ${spent:.4f} "
                      f"total ${prior + spent:.4f} | {round(time.time() - t_start)}s", flush=True)
                submit_next()
                break
    print(json.dumps({"run_spent_usd": round(spent, 4), "total_spent_usd": round(prior + spent, 4),
                      "wall_s": round(time.time() - t_start, 1)}), flush=True)


if __name__ == "__main__":
    main()
