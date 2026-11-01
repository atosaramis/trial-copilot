"""Build demo_cache/outcomes.json: the primary-outcome triage view (saved results, no API call).

    python3 scripts/build_outcome_view.py --work <scan folder>

The scan folder (kept outside the repo) holds the AACT-derived tables and the text of the posted
protocols, amendments and analysis plans. This script copies only short quotes, page numbers and
registry outcome titles into the saved file, and keeps a quote only if code finds it word for word
on the page it names. Protocol PDFs stay on ClinicalTrials.gov; the page links point there.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "demo_cache" / "outcomes.json"
SNAPS = [("2017-01-05", "p2017"), ("2018-01-11", "p2018"), ("2020-01-01", "p2020"), ("2023-01-02", "p2023")]

FUNNEL = [
    {"n": 1436, "label": "Trials with a posted protocol, all still running in Jan 2017",
     "how": "Public data: ClinicalTrials.gov via AACT snapshots (Jan 2017, Jan 2018, Jan 2020, Jan 2023) and the results section.",
     "who": "Code", "cost": 0.0},
    {"n": 1015, "label": "Primary-outcome text changed after Jan 2017",
     "how": "Fuzzy text comparison of the registered primary outcomes across the snapshots and the results section.",
     "who": "Code", "cost": 0.0},
    {"n": 234, "label": "The main measure itself looks different",
     "how": "Each of the 1,015 registry histories rated: wording only, timeframe, added, dropped, or a different measure.",
     "who": "Muse Spark 1.3 (bulk tier)", "cost": 0.31},
    {"n": 73, "label": "Protocol dated before the trial started",
     "how": "Document dates from the registry: only an early protocol shows what was planned before enrollment began.",
     "who": "Code", "cost": 0.0},
    {"n": 33, "label": "Flagged for review after reading the protocol",
     "how": "Protocol pages read with page-cited quotes; 69 of 73 quotes found word for word by code, the rest dropped.",
     "who": "Muse Spark 1.3", "cost": 1.62},
]
TRIAGE = {"wording only": 453, "no change": 20, "timeframe change": 208, "primary added": 99,
          "primary dropped or demoted": 62, "different measure": 172, "unclear": 1}
SPARK_CALLS = {"flagged": 33, "pre-start change": 32, "wording only": 5, "timeframe": 1, "unclear": 2}

# Each case: documents with short quotes (verified below), and a plain-words reading.
CASES = [
    {"nct": "NCT02623998", "role": "lead", "short": "REMIT-Sita",
     "title": "Sitagliptin-based metabolic intervention to induce remission of type 2 diabetes",
     "verdict": "Discrepancy requiring review", "tone": "review",
     "registered": "Drug-free diabetes remission at 24 weeks", "later": "Hyperglycemia relapse over 64 weeks of follow-up",
     "docs": [
        {"file": "Prot_000.pdf", "kind": "protocol", "label": "Protocol v2.0", "date": "2015-12-16", "page": 7,
         "quote": "The primary outcome in this trial is diabetes remission evaluated at 24 weeks after randomization."},
        {"file": "SAP_001.pdf", "kind": "sap", "label": "Statistical analysis plan, draft v1.1", "date": "2019-11-26", "page": 4,
         "quote": "The primary outcome in this trial will be hyperglycemia relapse at or after the 12-week visit."},
        {"file": "SAP_001.pdf", "kind": "sap_extra", "label": "Same plan, next sentence", "date": "2019-11-26", "page": 4,
         "quote": "Key secondary outcomes will be diabetes remission at 24, 36, 48 and 64 weeks"}],
     "reading": ["The protocol (v2.0, Dec 2015, before the first patient) names diabetes remission at 24 weeks as the primary outcome, and the registry said the same in Jan 2017 and Jan 2018.",
                 "By Jan 2020 the registry's primary outcome was hyperglycemia relapse over 64 weeks, and the posted results report that.",
                 "The only posted document with the new primary outcome is an analysis-plan draft dated Nov 26, 2019. It moves remission to a key secondary outcome.",
                 "Timing cuts both ways: the draft comes after the registered primary completion date (Sep 2018, which fits the original 24-week outcome), but four days before the registered study completion (Nov 30, 2019), so it may predate the final 64-week analysis.",
                 "A change like this can be legitimate. The posted documents don't say why it was made or what was known at the time, which is why it needs a person to look."],
     "would_change": "An earlier dated amendment naming relapse as primary, a record that the analysis plan was fixed before unblinding, or the published paper disclosing and explaining the change."},
    {"nct": "NCT02152631", "role": "cleared", "short": "JUNIPER",
     "title": "Abemaciclib vs erlotinib in KRAS-mutated non-small cell lung cancer",
     "verdict": "Explained by a dated amendment", "tone": "ok",
     "registered": "Co-primary: progression-free survival and overall survival", "later": "Overall survival only",
     "docs": [
        {"file": "Prot_001.pdf", "kind": "protocol", "label": "Original protocol", "date": "2014-05-13", "page": 40,
         "quote": "This study has co-primary efficacy measures of PFS and OS."},
        {"file": "Prot_002.pdf", "kind": "amendment", "label": "Protocol amendment (e)", "date": "2016-12-20", "page": 24,
         "quote": "PFS is removed as a co-primary endpoint and changed to a secondary endpoint. With this change OS becomes the sole primary endpoint."},
        {"file": "Prot_002.pdf", "kind": "amendment_extra", "label": "Same amendment, same page", "date": "2016-12-20", "page": 24,
         "quote": "While amending the protocol, the Lilly study team remains blinded to aggregate data and will not be unblinded until the final OS analysis"}],
     "reading": ["The original protocol had two co-primary outcomes, progression-free and overall survival, and the Jan 2017 registry still listed both.",
                 "Amendment (e), approved Dec 20, 2016 and posted with the results, removes progression-free survival as a co-primary outcome and gives the reason: the comparator's US label and treatment guidelines changed in Oct 2016. It also states the study team was still blinded to aggregate data.",
                 "The amendment was approved about nine months before the registered primary completion date (Sep 2017), and the registry showed overall survival alone by Jan 2018. The change is dated, explained and public, so it is cleared."],
     "would_change": "Evidence that the amendment was made after outcome data were seen."},
]
VERDICTS = ["needs_review", "timing_unsettled", "possible_data_entry_error", "probable", "explained"]
HOLDS = {"needs_review", "timing_unsettled", "possible_data_entry_error"}
# Code tag: primaries that were a safety or pharmacokinetic list (often reformatted when results are posted).
SAFETY_PK = re.compile(r"adverse|\bAEs?\b|safety|tolerab|\bPK\b|pharmacokin|Cmax|AUC|vital sign", re.I)


def group(review_class: str | None) -> str | None:
    if not review_class:
        return None
    if review_class.startswith("clean") or review_class in HOLDS:
        return "holds_up"
    return "probable" if review_class.startswith("probable") else "explained"


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w%.,;:()/<>=+-]", " ", s.lower())).strip()


def doc_url(nct: str, fname: str, page: int | None = None) -> str:
    u = f"https://cdn.clinicaltrials.gov/large-docs/{nct[-2:]}/{nct}/{fname}"
    return f"{u}#page={page}" if page else u


def verify(work: Path, nct: str, d: dict) -> dict:
    txt = work / "docs33" / f"{nct}_{Path(d['file']).stem}.txt"
    pages = txt.read_text(errors="ignore").split("\f")
    ok = 1 <= d["page"] <= len(pages) and norm(d["quote"]) in norm(pages[d["page"] - 1])
    if not ok:
        raise SystemExit(f"quote not found on the named page: {nct} {d['file']} p{d['page']}")
    return {**d, "url": doc_url(nct, d["file"], d["page"]), "verified": True}


def check_quote(work: Path, nct: str, fname: str, q: dict) -> bool:
    txt = work / "docs33" / f"{nct}_{Path(fname).stem}.txt"
    pages = txt.read_text(errors="ignore").split("\f")
    p, nq = q.get("page") or 0, norm(q.get("quote") or "")
    if len(nq) < 15 or not 1 <= p <= len(pages):
        return False
    return nq in norm(pages[p - 1]) or nq.replace(" ", "") in norm(pages[p - 1]).replace(" ", "")


def wonder_case(work: Path, nct: str, w: dict) -> dict:
    files = {d["id"]: d for d in w["docs"]}
    qs, dropped = [], 0
    for q in w.get("quotes", []):
        d = files.get(q.get("doc"))
        if d and check_quote(work, nct, d["file"], q) and len(q["quote"]) <= 280:
            qs.append({"quote": q["quote"], "page": q["page"], "shows": q.get("shows", ""), "label": d["label"], "date": d["date"],
                       "url": doc_url(nct, d["file"], q["page"]), "verified": True})
        else:
            dropped += 1
    e = w.get("explaining_document")
    expl, offered = None, int(isinstance(e, dict) and bool(e.get("quote")))
    if isinstance(e, dict) and files.get(e.get("doc")) and check_quote(work, nct, files[e["doc"]]["file"], e):
        d = files[e["doc"]]
        expl = {"quote": e["quote"], "page": e["page"], "label": d["label"], "date": d["date"], "url": doc_url(nct, d["file"], e["page"]), "verified": True}
    return {"verdict": w["verdict"], "original": w["original_primary"], "later": w["later_primary"], "timing": w["decision_timing"],
            "reason": w["reason"], "would_change": w["what_would_change"], "quotes": qs, "dropped": dropped, "explaining": expl,
            "safety_pk": bool(SAFETY_PK.search(w["original_primary"])), "explaining_offered": offered, "input_notes": w.get("input_notes", [])}


def load(work: Path):
    diff = {r["nct"]: r for r in csv.DictReader(open(work / "code_diff.csv"))}
    studies = {r["nct_id"]: r for r in csv.DictReader(open(work / "data" / "studies_2023.txt"), delimiter="|", quoting=csv.QUOTE_NONE)}
    sponsors = {}
    for p in (work / "ctgov").glob("NCT*.json"):
        j = json.loads(p.read_text())["protocolSection"]
        sponsors[j["identificationModule"]["nctId"]] = j["sponsorCollaboratorsModule"]["leadSponsor"]["name"]
    return diff, studies, sponsors


def dates(nct, studies):
    s = studies[nct]
    return {"registered": s["study_first_submitted_date"], "start": s["start_date"],
            "primary_completion": s["primary_completion_date"], "completion": s["completion_date"], "results_posted": s["results_first_posted_date"]}


def registry(nct, diff):
    r = diff[nct]
    out = []
    for date, col in SNAPS:
        v = json.loads(r[col]) if r.get(col) not in (None, "", "null") else None
        out.append({"date": date, "outcomes": [{"measure": m, "timeframe": t} for m, t in (v or [])][:4],
                    "more": max(0, len(v or []) - 4)})
    v = json.loads(r["pres"]) if r.get("pres") not in (None, "", "null") else None
    res = {"outcomes": [{"measure": m, "timeframe": t} for m, t in (v or [])][:4], "more": max(0, len(v or []) - 4)}
    return out, res


def timeline(c, ds, reg, res):
    ev = [{"date": ds["registered"], "kind": "marker", "label": "First registered"},
          {"date": ds["start"], "kind": "marker", "label": "Trial start"},
          {"date": ds["primary_completion"], "kind": "marker", "label": "Primary completion (registered)"},
          {"date": ds["completion"], "kind": "marker", "label": "Study completion (registered)"}]
    for d in c["docs"]:
        if not d["kind"].endswith("_extra"):
            ev.append({"date": d["date"], "kind": d["kind"], "label": d["label"], "quote": d["quote"], "page": d["page"], "url": d["url"]})
    prev = None
    for r in reg:
        key = json.dumps([o["measure"].lower() for o in r["outcomes"]])
        ev.append({"date": r["date"], "kind": "registry", "label": "Registry record", "outcomes": r["outcomes"], "more": r["more"],
                   "first_change": prev is not None and key != prev and not any(e.get("first_change") for e in ev)})
        prev = key
    if ds["results_posted"]:
        ev.append({"date": ds["results_posted"], "kind": "results", "label": "Results posted", "outcomes": res["outcomes"], "more": res["more"]})
    order = {"marker": 0, "protocol": 1, "amendment": 1, "sap": 1, "registry": 2, "results": 3}
    return sorted(ev, key=lambda e: (e["date"], order[e["kind"]]))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True, help="scan folder outside the repo")
    work = Path(ap.parse_args().work)
    diff, studies, sponsors = load(work)
    earlier = {r["nct_id"]: r["review_class"] for r in csv.DictReader(open(work / "reviewed_cases.csv"))}
    ledger = json.loads((work / "wonder" / "ledger.json").read_text())
    W = {}
    for n in (work / "real33.txt").read_text().split():
        W[n] = wonder_case(work, n, json.loads((work / "wonder" / f"{n}.json").read_text()))
        W[n].update(nct=n, title=studies[n]["brief_title"], dates=dates(n, studies), record_url=f"https://clinicaltrials.gov/study/{n}",
                    history_url=f"https://clinicaltrials.gov/study/{n}?tab=history", earlier=group(earlier.get(n)))
    counts = {v: sum(w["verdict"] == v for w in W.values()) for v in VERDICTS}
    pairs = [(group(earlier[n]), group(W[n]["verdict"])) for n in earlier]
    agree3 = sum(a == b for a, b in pairs)
    agree2 = sum((a == "explained") == (b == "explained") for a, b in pairs)
    po = agree3 / len(pairs)
    ca = {k: sum(a == k for a, _ in pairs) for k in ("holds_up", "probable", "explained")}
    cb = {k: sum(b == k for _, b in pairs) for k in ca}
    pe = sum(ca[k] * cb[k] for k in ca) / len(pairs) ** 2
    agreement = {"n": len(pairs), "three_groups": agree3, "explained_or_not": agree2, "kappa": round((po - pe) / (1 - pe), 2),
                 "differs": [{"nct": n, "earlier": group(earlier[n]), "wonder": W[n]["verdict"]} for n in earlier
                             if group(earlier[n]) != group(W[n]["verdict"])]}
    quotes_ok = sum(len(w["quotes"]) + bool(w["explaining"]) for w in W.values())
    quotes_all = sum(len(w["quotes"]) + w["dropped"] + w["explaining_offered"] for w in W.values())
    not_expl = [w for w in W.values() if w["verdict"] != "explained"]
    short = [w for w in not_expl if w["verdict"] in HOLDS and not w["safety_pk"]]
    short.sort(key=lambda w: (w["nct"] != "NCT02623998", w["earlier"] != "holds_up", w["verdict"] != "needs_review", w["nct"]))
    probable = [w for w in not_expl if w["verdict"] == "probable" and not w["safety_pk"]]
    safety = [w for w in not_expl if w["safety_pk"]]
    explained = [w for w in W.values() if w["verdict"] == "explained"]
    wonder_cost = round(ledger["spent"], 2)
    funnel = FUNNEL[:5] + [
        {"n": len(not_expl), "label": "Not explained by the trial's own documents",
         "how": f"Every posted protocol, amendment and analysis plan read in full ({counts['explained']} explained). {quotes_ok} of {quotes_all} quotes found on the cited page by code; the rest dropped.",
         "who": "Muse Wonder 1.0", "cost": wonder_cost},
        {"n": len(short), "label": "Shortlist for expert review",
         "how": f"Efficacy outcomes judged 'needs review' or 'timing can't be settled'. Set aside: {len(probable)} probable and {len(safety)} safety or pharmacokinetic outcome lists (listed below).",
         "who": "Code", "cost": 0.0}]
    cases = []
    for c in CASES:
        c = {**c, "docs": [verify(work, c["nct"], d) for d in c["docs"]]}
        ds = dates(c["nct"], studies)
        reg, res = registry(c["nct"], diff)
        c.update(dates=ds, sponsor=sponsors.get(c["nct"]), registry=reg, results=res, timeline=timeline(c, ds, reg, res), wonder=W[c["nct"]],
                 record_url=f"https://clinicaltrials.gov/study/{c['nct']}", history_url=f"https://clinicaltrials.gov/study/{c['nct']}?tab=history")
        cases.append(c)
    out = {"funnel": funnel, "triage": TRIAGE, "spark_calls": SPARK_CALLS, "wonder_counts": counts, "wonder_cost": wonder_cost,
           "wonder_tokens": {"input": sum(x["prompt_tokens"] for x in ledger["calls"]), "output": sum(x["completion_tokens"] for x in ledger["calls"])},
           "quotes": {"kept": quotes_ok, "offered": quotes_all}, "agreement": agreement,
           "total_cost": round(sum(f["cost"] for f in funnel) + 0.02, 2), "cases": cases, "shortlist": short, "probable": probable,
           "safety_pk": safety, "explained": explained, "snapshots": [d for d, _ in SNAPS],
           "trimmed": {n: w["input_notes"] for n, w in W.items() if w["input_notes"]}}
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print("wrote", OUT, "counts", counts, "shortlist", len(short), "quotes", quotes_ok, "/", quotes_all, "agreement", agreement)


if __name__ == "__main__":
    sys.exit(main())
