"""Build demo_cache/mismatch.json for the mismatch-check screen from saved results (no API call).

For each demo trial, and for a few tuning-set examples: the finder's v3 output (compared fields,
mismatches with page and quote, cleared look-alikes), the registry's design fields in the Jan 2017,
Jan 2020 and Jan 2023 AACT snapshots (only for fields that mismatch), the auto-grade, and the saved
agent verdict with its code-verified citations. Plus the tuning-set validation numbers.

Only design fields are read from the snapshots (sites, countries, enrollment, phase, allocation,
arms). Trial status, stop reasons and outcome labels are never read. From the cohort file only
nct_id and protocol_doc_url are loaded.

    python -m scripts.build_mismatch_view --cards DIR --tuning-cards DIR --registry PARQUET \
        --text DIR --aact DIR --cohort CSV --agent-demos DIR --agent-candidates DIR \
        --agent-baseline DIR --candidate-ids JSON --scan-v2 JSON --scan-v3 JSON
"""
from __future__ import annotations

import argparse
import collections as C
import json
from pathlib import Path

import pandas as pd

from app.mismatch.agent import agreement
from app.mismatch.autograde import grade, load_snapshot
from app.mismatch.finder import READING_TRAPS, find_mismatches, load_pages
from scripts.mismatch_agent_run import REG_KEYS, SNAPS, load_card

ROOT = Path(__file__).resolve().parents[1]
DEMOS = ["NCT02720510", "NCT01857271", "NCT02735980", "NCT02155660", "NCT02760602"]
# Tuning-set examples (not held out): one of each kind a reviewer meets, including disagreements.
EXAMPLES = [("NCT01206764", "sites"), ("NCT02053350", "randomized"), ("NCT01988090", "sites"),
            ("NCT02308046", "enrollment"), ("NCT02778399", "sites"), ("NCT02740543", "enrollment")]
SNAP_ATTR = {"sites": "n_sites", "countries": "n_countries", "enrollment": "enrollment", "phase": "phase",
             "randomized": "allocation", "arms": "n_arms"}


def _num(v):
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def _snap_value(s, field):
    v = getattr(s, SNAP_ATTR[field])
    if field == "enrollment" and v is not None and s.enrollment_type:
        return f"{_num(v)} ({s.enrollment_type.lower()})"
    return _num(v)


def trial_view(n, card, pages_meta, reg_row, pages, snaps, agent_rec, url, only_field=None):
    res = find_mismatches(n, card, reg_row, pages, rules="v3")
    findings = {f["field"]: f for f in (agent_rec or {}).get("findings") or []}
    later = [snaps[t][n] for t in ("2020", "2023") if n in snaps[t]]
    out = []
    for m in res.mismatches:
        if only_field and m.field != only_field:
            continue
        g = grade(m, later, rules="v3")
        f = findings.get(m.field)
        tl = [{"year": t, "value": _snap_value(snaps[t][n], m.field) if n in snaps[t] else None}
              for _, t in SNAPS]
        out.append({
            "field": m.field, "protocol_value": _num(m.protocol_value), "registry_value": _num(m.registry_value),
            "severity": m.severity, "traps": list(m.traps), "doubtful": m.doubtful_reading, "note": m.note,
            "page": m.evidence.page, "quote": m.evidence.quote, "evidence_kind": m.evidence.kind,
            "timeline": tl, "auto": g.category, "auto_reason": g.reason,
            "agent": None if f is None else {
                "verdict": f["verdict"], "explanation": f["explanation"],
                "citations": f["protocol_citations"], "registry_citations": f["registry_citations"],
                "dropped": len(f.get("dropped") or []),
                "agrees": agreement(f["verdict"], g.category)},
        })
    return {"nct_id": n, "protocol_url": url,
            "compared": [{"field": c, "protocol": _num(_cval(card, c)), "registry_2017": _num(_rval(reg_row, c))}
                         for c in res.compared if not only_field],
            "mismatches": out,
            "cleared": [] if only_field else [{"field": m.field, "protocol_value": _num(m.protocol_value),
                                               "registry_value": _num(m.registry_value), "traps": list(m.traps),
                                               "page": m.evidence.page, "quote": m.evidence.quote, "note": m.note}
                                              for m in res.cleared]}


def _cval(card, field):
    return {"sites": card.get("planned_sites"), "countries": card.get("planned_countries"),
            "enrollment": card.get("planned_enrollment"), "phase": card.get("phase"),
            "randomized": card.get("allocation"), "arms": card.get("n_arms")}.get(field)


def _rval(r, field):
    return {"sites": r.get("n_sites_2017"), "countries": r.get("n_countries"), "enrollment": r.get("enrollment"),
            "phase": r.get("phase"), "randomized": r.get("allocation"), "arms": r.get("n_arms")}.get(field)


def _rows(d: Path, ids):
    rows = []
    for n in ids:
        x = json.loads((d / f"{n}.json").read_text())
        rows += [dict(f, nct=n) for f in x.get("findings") or []]
    return rows


def summarise(rows):
    s = [r for r in rows if r["agrees_with_auto"] is not None]
    sn = [r for r in s if r["field"] != "arms"]
    v = C.Counter(r["verdict"] for r in rows)
    quotes = sum(len(r["protocol_citations"]) for r in rows)
    dropped = sum(len(r.get("dropped") or []) for r in rows)
    return {"mismatches": len(rows), "trials": len({r["nct"] for r in rows}), "verdicts": dict(v),
            "extraction_error": v["extraction_error"],
            "settled": len(s), "agree": sum(r["agrees_with_auto"] for r in s),
            "settled_no_arms": len(sn), "agree_no_arms": sum(r["agrees_with_auto"] for r in sn),
            "quotes_kept": quotes, "quotes_offered": quotes + dropped,
            "doubtful": sum(1 for r in rows if READING_TRAPS & set(r["traps"])),
            "disagreements": sorted(f"{r['nct']} {r['field']}" for r in s if not r["agrees_with_auto"])}


def main():
    ap = argparse.ArgumentParser()
    for a in ("cards", "tuning-cards", "registry", "text", "aact", "cohort", "agent-demos", "agent-candidates",
              "agent-baseline", "candidate-ids", "scan-v2", "scan-v3"):
        ap.add_argument(f"--{a}", required=True)
    ap.add_argument("--out", default=str(ROOT / "demo_cache" / "mismatch.json"))
    a = ap.parse_args()
    ids = DEMOS + [n for n, _ in EXAMPLES]
    reg = pd.read_parquet(a.registry, columns=["nct_id", *REG_KEYS]).set_index("nct_id")
    urls = pd.read_csv(a.cohort, usecols=["nct_id", "protocol_doc_url"]).set_index("nct_id")["protocol_doc_url"]
    snaps = {tag: load_snapshot(Path(a.aact) / sub, tag, ids) for sub, tag in SNAPS}
    demo_cache = {p.stem: json.loads(p.read_text()) for p in (ROOT / "demo_cache").glob("NCT*.json")}

    def build(n, cards, agent_dir, only=None):
        card, pm = load_card(Path(cards), n)
        r = {k: (None if pd.isna(v) else v) for k, v in reg.loc[n].items()}
        txt = Path(a.text) / f"{n}.txt"
        pages = load_pages(txt) if txt.exists() else []
        f = Path(agent_dir) / f"{n}.json"
        rec = json.loads(f.read_text()) if f.exists() else None
        url = (demo_cache.get(n) or {}).get("protocol_url") or urls.get(n)
        return trial_view(n, card, pm, r, pages, snaps, rec, url, only)

    demos = []
    for n in DEMOS:
        v = build(n, a.cards, a.agent_demos)
        dc = demo_cache[n]
        v.update(label=dc["label"], title=dc.get("registry_title_2017"))
        demos.append(v)
    examples = []
    for n, fld in EXAMPLES:
        v = build(n, a.tuning_cards, a.agent_candidates, fld)
        assert v["mismatches"], (n, fld)
        examples.append(v)
    cid = json.loads(Path(a.candidate_ids).read_text())["ids"]
    v2s, v3s = (json.loads(Path(p).read_text()) for p in (a.scan_v2, a.scan_v3))
    keep = ("trials_with_cards", "mismatches", "trials_with_mismatch", "settled", "ambiguous", "categories")
    val = {"candidates": {"v3": summarise(_rows(Path(a.agent_candidates), cid)),
                          "v2": summarise(_rows(Path(a.agent_baseline), cid))},
           "scan": {"v2": {k: v2s.get(k) for k in keep}, "v3": {k: v3s.get(k) for k in keep},
                    "ambiguous_reasons": v3s.get("ambiguous_reasons")}}
    Path(a.out).write_text(json.dumps({"rules": "v3", "demos": demos, "examples": examples, "validation": val},
                                      indent=1, default=str) + "\n")
    print(f"wrote {a.out}: {sum(len(d['mismatches']) for d in demos)} demo mismatches, {len(examples)} examples")


if __name__ == "__main__":
    main()
