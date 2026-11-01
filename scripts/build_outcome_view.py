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
    {"n": 6, "label": "Shortlist for expert review",
     "how": "12 of the 33 checked so far against posted amendments and analysis plans: 3 hold up, 3 probable, 6 explained by the documents.",
     "who": "AI-assisted document review", "cost": 0.02},
]
TRIAGE = {"wording only": 453, "no change": 20, "timeframe change": 208, "primary added": 99,
          "primary dropped or demoted": 62, "different measure": 172, "unclear": 1}
SPARK_CALLS = {"flagged": 33, "pre-start change": 32, "wording only": 5, "timeframe": 1, "unclear": 2}
REVIEW = {"checked": 12, "holds_up": 3, "probable": 3, "explained": 6}

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
SHORTLIST = [
    {"nct": "NCT02623998", "status": "holds up", "note": "Lead case above."},
    {"nct": "NCT02069847", "status": "holds up", "registered": "Dysphagia score at 3 months",
     "later": "Dysplasia in Barrett esophagus at 3 months",
     "doc": {"file": "Prot_SAP_000.pdf", "label": "Protocol and analysis plan", "date": "2013-12-11", "page": 9,
             "quote": "Measure the incidence of dysphagia following ESD or EMR in both historic control group and study intervention group."},
     "note": "Changed in the record between Jan 2020 and Jan 2023; results were submitted after primary completion. May be a data-entry error; still needs a look."},
    {"nct": "NCT02737930", "status": "holds up", "registered": "Improvement in size of visual field deficit (degrees) at 6 months",
     "later": "Percent change in binocularly averaged perimetric mean deviation, baseline to 6 months",
     "doc": {"file": "Prot_SAP_000.pdf", "label": "Protocol and analysis plan", "date": "2016-03-15", "page": 14,
             "quote": "The primary endpoint will be an improvement in peripheral vision of at least 15 degrees in the affected visual field as measured by automated Humphrey perimetry at 6 months."},
     "note": "Trial ended early. The record changed between Jan 2020 and Jan 2023, a window that spans primary completion (Aug 2020), so the order can't be settled from snapshots."},
    {"nct": "NCT02270255", "status": "probable", "registered": "Reduction in subjective pain after the procedure, 10 days",
     "later": "Morphine-equivalent dose used until recovery-room discharge, 6 hours",
     "doc": {"file": "Prot_SAP_000.pdf", "label": "Protocol v3", "date": "2014-12-02", "page": 14,
             "quote": "Reduction in subjective pain as measured by patient self administration of visual analogue scale and reduction in use of oral"},
     "note": "Partial overlap: the protocol's primary included analgesic use, but the 10-day pain score is gone."},
    {"nct": "NCT01275339", "status": "probable", "registered": "Three primaries: LV mass (MRI), diastolic function (tissue Doppler e'), LV strain",
     "later": "Diastolic function (tissue Doppler e') only",
     "doc": {"file": "Prot_SAP_000.pdf", "label": "Protocol", "date": "2012-11-01", "page": 10,
             "quote": "1) Change in diastolic function as measured by tissue Doppler e’ on echo from baseline to 6 months 2) Change in LV longitudinal peak systolic strain by echo from baseline to 6 months"},
     "note": "A protocol co-primary (strain) is no longer listed as primary from Jan 2020 on. Pilot study."},
    {"nct": "NCT02819011", "status": "probable", "registered": "Gait speed and balance change at 1, 3 and 6 months",
     "later": "Hip, ankle and center-of-mass sway change at 6 months",
     "doc": {"file": "Prot_000.pdf", "label": "Protocol", "date": "2015-10-16", "page": 3,
             "quote": "Characterize the impact of AFO on balance, gait, risk of falling, frailty status, and adverse events"},
     "note": "The protocol's primary is broad, so the later sway measures may be one reading of it. The 2018 analysis plan is a scanned image and was not read."},
]
EXPLAINED = [
    {"nct": "NCT02152631", "why": "Dated amendment (e), Dec 2016, removes PFS as co-primary (case above)."},
    {"nct": "NCT03007888", "why": "The record moved to pharmacokinetic measures, and the protocol's primary objective is pharmacokinetic.",
     "doc": {"file": "Prot_000.pdf", "label": "Protocol amendment 2", "date": "2016-10-05", "page": 21,
             "quote": "To compare the pharmacokinetics (PK) of single and multiple doses of IPX203 with immediate release (IR) CD-LD"}},
    {"nct": "NCT01955980", "why": "Pilot study: the 2020 analysis plan says no primary endpoint was defined in advance (scanned plan, read with Muse Spark vision)."},
    {"nct": "NCT02584660", "why": "The registry dropped a bleeding co-primary that the protocol never had; the record now matches the protocol.",
     "doc": {"file": "Prot_000.pdf", "label": "Protocol", "date": "2015-06-16", "page": 7,
             "quote": "The primary clinical endpoint is the number of days of initial inpatient hospitalization"}},
    {"nct": "NCT02682381", "why": "The registry dropped a safety co-primary; the protocol's primary was always the nutrition-volume reduction.",
     "doc": {"file": "Prot_000.pdf", "label": "Protocol", "date": "2015-03-12", "page": 20,
             "quote": "A 20% reduction or greater (including complete weaning) from baseline in volume of PN/IV at the end of 24 weeks of treatment was used as the primary endpoint"}},
    {"nct": "NCT02640807", "why": "The registry dropped a tolerance co-primary; the protocol's primary was always the lymphocyte-count increase.",
     "doc": {"file": "Prot_000.pdf", "label": "Protocol v1.4", "date": "2015-12-14", "page": 34,
             "quote": "Primary endpoint: increase of ALC by greater than 50% from baseline by day 42"}},
]


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
    cases = []
    for c in CASES:
        c = {**c, "docs": [verify(work, c["nct"], d) for d in c["docs"]]}
        ds = dates(c["nct"], studies)
        reg, res = registry(c["nct"], diff)
        c.update(dates=ds, sponsor=sponsors.get(c["nct"]), registry=reg, results=res, timeline=timeline(c, ds, reg, res),
                 record_url=f"https://clinicaltrials.gov/study/{c['nct']}", history_url=f"https://clinicaltrials.gov/study/{c['nct']}?tab=history")
        cases.append(c)
    short = []
    for s in SHORTLIST:
        s = dict(s)
        if "doc" in s:
            s["doc"] = verify(work, s["nct"], s["doc"])
        s.update(title=studies[s["nct"]]["brief_title"], sponsor=sponsors.get(s["nct"]), dates=dates(s["nct"], studies),
                 record_url=f"https://clinicaltrials.gov/study/{s['nct']}")
        short.append(s)
    expl = []
    for e in EXPLAINED:
        e = dict(e)
        if "doc" in e:
            e["doc"] = verify(work, e["nct"], e["doc"])
        e.update(title=studies[e["nct"]]["brief_title"], record_url=f"https://clinicaltrials.gov/study/{e['nct']}")
        expl.append(e)
    out = {"funnel": FUNNEL, "triage": TRIAGE, "spark_calls": SPARK_CALLS, "review": REVIEW,
           "total_cost": round(sum(f["cost"] for f in FUNNEL), 2), "cases": cases, "shortlist": short, "explained": expl,
           "snapshots": [d for d, _ in SNAPS]}
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print("wrote", OUT, "quotes verified:", sum(len(c["docs"]) for c in cases) + sum("doc" in x for x in short + expl))


if __name__ == "__main__":
    sys.exit(main())
