"""The sponsor memo (build spec section 2, step 5): Muse Wonder writes, code checks.

1. `build_evidence()` turns the trial card, the search trace and the code-computed risk numbers
   into numbered facts (F1, F2, ...) plus lists of past comparable and competing trials with
   their NCT IDs. Everything is from the Jan 5, 2017 registry snapshot. The audited trial's own
   NCT ID is never in the pack, so Wonder can't recall how it went.
2. `muse-wonder-1.0` writes 3-5 bottlenecks as JSON. It may only cite facts, numbers and NCT
   IDs from the pack and never computes anything.
3. `check_memo()` checks every NCT ID against the pack (anything else becomes "unverified
   citation removed"), every number against the pack's numbers (allowing only rounding), every
   [F#] tag, and the banned framing words. The memo shows the result.
"""
from __future__ import annotations

import json
import math
import os
import re
import time
from pathlib import Path

from .framing import BANNED_FRAMING
from .risk import what_if
from .tools import RegistryTools

MODEL = "muse-wonder-1.0"
BASE_URL = "https://api.meta.ai/v1"
PRICES = {"muse-wonder-1.0": (4e-6, 20e-6)}  # USD per token: input, output (incl. reasoning)
PROMPT = Path(__file__).parent / "prompts" / "memo_wonder.txt"
MAX_STOPPED, MAX_COMPLETED, MAX_COMPETING = 12, 6, 8
REMOVED_ID = "[unverified citation removed]"
REMOVED_NUM = "[unverified number removed]"
NCT_RX = re.compile(r"\bNCT\d{8}\b")
TAG_RX = re.compile(r"\[(F\d+(?:\s*,\s*F\d+)*)\]")
NUM_RX = re.compile(r"(?<![A-Za-z0-9.])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(?![\d])")
TEXT_KEYS = ("headline", "evidence_limits")
# Overall verdicts the headline must not give (the memo states risks; the sponsor decides).
VERDICT_RX = re.compile(r"\b(?:in)?feasib(?:le|ility looks)|\bnot feasible|\bachievable|\brealistic|\bon track|"
                        r"\blooks? (?:fine|good|ok|okay|reasonable|manageable)|\blikely to (?:succeed|fail)|"
                        r"\bwill (?:succeed|fail)|\bno (?:major|significant) (?:risk|concern)s?\b|\blow[- ]risk\b",
                        re.I)
BOTTLENECK_TEXT = ("title", "evidence", "what_to_check")


class MemoError(RuntimeError):
    pass


# ----------------------------------------------------------------------------- evidence pack
def _pct(x):
    return None if x is None else f"{100 * x:.1f}%"


def _num(x, nd=2):
    if x is None:
        return None
    if isinstance(x, float) and not x.is_integer():
        return f"{x:.{nd}f}"
    return f"{int(x):,}"


def _pages(pages, field):
    p = (pages or {}).get(field)
    return f" (protocol p. {', '.join(str(i) for i in p)})" if p else ""


def _args_text(args: dict) -> str:
    parts = []
    for k, v in args.items():
        if v in (None, [], ""):
            continue
        parts.append(f"{k.replace('_', ' ')}={', '.join(map(str, v)) if isinstance(v, list) else v}")
    return "; ".join(parts)


def build_evidence(card: dict, audit: dict, pools_dir=None, nct_id: str | None = None,
                   pages: dict | None = None, card_flags: list | None = None) -> dict:
    """Facts and trial lists for the memo, plus every number and NCT ID they contain."""
    facts: list[tuple[str, list]] = []  # (text, raw values used for the rounding check)

    def add(text, *raw):
        if text:
            facts.append((text, [r for r in raw if isinstance(r, (int, float)) and not isinstance(r, bool)]))

    c = card
    add(f"Draft protocol: {c.get('condition') or 'condition not read'}; {c.get('phase') or 'phase not read'}; "
        f"{c.get('n_arms') or '?'} arms; {c.get('allocation') or 'allocation not read'}; masking: "
        f"{c.get('masking') or 'not read'}; placebo arm: {'yes' if c.get('placebo_arm') else 'no'}; "
        f"sponsor type: {c.get('sponsor_type') or 'not read'}{_pages(pages, 'phase')}.")
    if c.get("interventions"):
        add(f"Study drugs: {c['interventions']}{_pages(pages, 'interventions')}.")
    risk = audit.get("risk") or {}
    sp = risk.get("site_pace") or {}
    reg = audit.get("registry_2017_used") or {}
    if c.get("planned_enrollment"):
        add(f"Planned enrollment: {_num(c['planned_enrollment'])} participants{_pages(pages, 'planned_enrollment')}.",
            c["planned_enrollment"])
    if c.get("planned_sites") or sp.get("registry_sites_2017"):
        add(f"Sites: protocol says {_num(c.get('planned_sites')) or 'not stated'}"
            f"{_pages(pages, 'planned_sites')}; the Jan 2017 registry record lists "
            f"{_num(sp.get('registry_sites_2017')) or 'none'}.", c.get("planned_sites"), sp.get("registry_sites_2017"))
    add("Enrollment period: " + (f"{_num(c['enrollment_period_months'])} months{_pages(pages, 'enrollment_period_months')}."
                                 if c.get("enrollment_period_months") else "not stated in the protocol."),
        c.get("enrollment_period_months"))
    if reg.get("countries"):
        n_c = len([x for x in str(reg["countries"]).split(",") if x.strip()])
        add(f"Countries in the Jan 2017 registry record ({n_c}): {reg['countries']}.", n_c)
    elig = []
    if c.get("min_age_years") is not None or c.get("max_age_years") is not None:
        elig.append(f"age {c.get('min_age_years') if c.get('min_age_years') is not None else '?'} to "
                    f"{c.get('max_age_years') if c.get('max_age_years') is not None else 'no upper limit'}")
    for k, label in (("performance_status_requirement", "performance status"), ("max_prior_lines", "prior therapy"),
                     ("required_biomarker", "required biomarker"), ("brain_mets_allowed", "brain metastases"),
                     ("washout_days_max", "longest washout (days)")):
        if c.get(k) not in (None, ""):
            elig.append(f"{label}: {c[k]}")
    if elig:
        add("Eligibility as read: " + "; ".join(elig) + f"{_pages(pages, 'age_criterion')}.",
            c.get("min_age_years"), c.get("max_age_years"), c.get("washout_days_max"))
    if c.get("clinic_visits_first_26_weeks") is not None:
        add(f"Visits (counted by code, one participant on treatment): {c['clinic_visits_first_26_weeks']} clinic visits "
            f"in the first 26 weeks and {c.get('clinic_visits_first_12_weeks')} in the first 12 weeks; "
            f"{c.get('remote_visits_first_26_weeks') or 0} remote visits in 26 weeks; screening window "
            f"{c.get('screening_window_days') if c.get('screening_window_days') is not None else 'not stated'} days with "
            f"{c.get('screening_clinic_visits')} screening clinic visit(s){_pages(pages, 'visit_schedule')}.",
            c["clinic_visits_first_26_weeks"], c.get("clinic_visits_first_12_weeks"), c.get("remote_visits_first_26_weeks"),
            c.get("screening_window_days"), c.get("screening_clinic_visits"), 26, 12)
    if c.get("soc_invasive_procedures_first_26_weeks") is not None:
        add(f"Mandated invasive procedures in the first 26 weeks (counted by code): "
            f"{c['soc_invasive_procedures_first_26_weeks']} standard of care, "
            f"{c.get('research_invasive_procedures_first_26_weeks')} research only; mandatory research biopsy: "
            f"{'yes' if c.get('mandatory_fresh_biopsy') else 'no'}; protocol-required surgery: "
            f"{'yes' if c.get('major_procedure_required') else 'no'}; inpatient stay required: "
            f"{'yes' if c.get('inpatient_stay_required') else 'no'}{_pages(pages, 'invasive_procedures')}.",
            c["soc_invasive_procedures_first_26_weeks"], c.get("research_invasive_procedures_first_26_weeks"), 26)

    search = audit.get("search") or {}
    for st in search.get("steps") or []:
        rows = st.get("rows")
        add(f"Search step {st['step']}: {st['tool'].replace('_', ' ')} ({_args_text(st.get('args') or {})}) "
            f"{'returned ' + _num(rows) + ' trials' if rows is not None else st.get('status')}. "
            f"Agent's reason: \"{(st.get('reason') or '').strip()}\".", st["step"], rows)
    comp = risk.get("comparable_trials")
    if comp:
        oc = comp.get("outcome_counts") or {}
        lo, hi = comp["ci95"]
        add(f"Comparable past trials chosen ({(audit.get('comparable') or {}).get('result_id')}): {_num(comp['n'])} trials; "
            f"{comp['events']} had stopped for poor enrollment by Jan 2017 = {_pct(comp['rate'])} "
            f"(95% CI {_pct(lo)} to {_pct(hi)}). Others: {oc.get('completed', 0)} completed, "
            f"{oc.get('terminated_other', 0)} stopped for other reasons, {oc.get('terminated_unknown_reason', 0)} "
            f"stopped with no reason given.", comp["n"], comp["events"], comp["rate"], lo, hi, *oc.values())
    pool = risk.get("all_trials_in_pool")
    if pool:
        lo, hi = pool["ci95"]
        add(f"All {_num(pool['n'])} past trials in the pool: {_num(pool['events'])} poor-enrollment stops = "
            f"{_pct(pool['rate'])} (95% CI {_pct(lo)} to {_pct(hi)}).", pool["n"], pool["events"], pool["rate"], lo, hi)
    if risk.get("relative_to_pool") is not None:
        add(f"The comparable stop rate is {risk['relative_to_pool']} times the pool rate (computed by code).",
            risk["relative_to_pool"])
    q = (risk.get("slider_model") or {}).get("pace_quantiles") or []
    if sp.get("patients_per_site_per_month") is not None:
        add(f"Enrollment pace needed: {sp['patients_per_site_per_month']:.2f} participants per site per month "
            f"({_num(sp.get('planned_enrollment'))} participants, {_num(sp.get('sites'))} sites from the "
            f"{str(sp.get('sites_source')).replace('_', ' ')}, {_num(sp.get('months'), 0)} months from the "
            f"{str(sp.get('months_source')).replace('_', ' ')}).",
            sp["patients_per_site_per_month"], sp.get("planned_enrollment"), sp.get("sites"), sp.get("months"))
        med, iqr = sp.get("comparable_completed_median_pace"), sp.get("comparable_completed_iqr") or [None, None]
        if med is not None:
            add(f"Completed comparables enrolled a median {med:.2f} participants per site per month "
                f"(middle half {iqr[0]:.2f} to {iqr[1]:.2f}); {_pct(sp.get('share_of_completed_comparables_at_least_this_fast'))} "
                f"of them were at least as fast as this protocol needs.",
                med, iqr[0], iqr[1], sp.get("share_of_completed_comparables_at_least_this_fast"))
            if sp.get("months") and sp.get("planned_enrollment"):
                need = math.ceil(sp["planned_enrollment"] / (med * sp["months"]))
                add(f"Sites needed to match the comparables' median pace over the same "
                    f"{_num(sp['months'], 0)} months: {need} (computed by code).", need, sp["months"])
        alt = sp.get("registry_sites_2017")
        if q and alt and sp.get("sites") and alt != sp["sites"] and sp.get("months"):
            w = what_if(sp["planned_enrollment"], alt, sp["months"], q)
            add(f"What-if (code): with the registry's {alt} sites instead, the pace needed is "
                f"{w['patients_per_site_per_month']:.2f}, and "
                f"{_pct(w['share_of_completed_comparables_at_least_this_fast'])} of completed comparables were at least that fast.",
                alt, w["patients_per_site_per_month"], w["share_of_completed_comparables_at_least_this_fast"])
    ct = risk.get("competing_trials")
    if ct:
        a = ct.get("args") or {}
        add(f"Competing trials recruiting on Jan 5, 2017 ({_args_text(a)}): {_num(ct['n_recruiting_jan_2017'])} trials "
            f"at {_num(ct['total_sites'])} sites in total.", ct["n_recruiting_jan_2017"], ct["total_sites"], 5, 2017)
    for f in (risk.get("flags") or []) + [f for f in (card_flags or []) if "procedure" in f or "screening" in f
                                          or "sites" in f or "enrollment" in f][:4]:
        add(f"Caveat: {f}.")

    # Trial lists (Jan 2017 records only), rebuilt from the saved search arguments.
    stopped, completed, competing = [], [], []
    if pools_dir is not None and (audit.get("comparable") or audit.get("competing")):
        tools = RegistryTools(pools_dir, exclude_nct=nct_id, target_enrollment=c.get("planned_enrollment"))
        if audit.get("comparable"):
            tools.search_comparable_trials(**audit["comparable"]["args"])
            rows = tools.results["S1"]["rows"]
            stopped = [r for r in rows if r.get("outcome_2017") == "terminated_poor_enrollment"][:MAX_STOPPED]
            target = c.get("planned_enrollment") or 0
            done = [r for r in rows if r.get("outcome_2017") == "completed" and r.get("enrollment")]
            completed = sorted(done, key=lambda r: abs((r["enrollment"] or 0) - target))[:MAX_COMPLETED]
        if audit.get("competing"):
            ca = (risk.get("competing_trials") or {}).get("args") or {}
            if ca.get("condition_terms"):
                tools.count_competing_trials(ca["condition_terms"], ca.get("phase") or None, ca.get("countries") or None)
                rid = [k for k in tools.results if k.startswith("C")][-1]
                competing = sorted(tools.results[rid]["rows"], key=lambda r: -(r.get("n_sites_2017") or 0))[:MAX_COMPETING]

    def yr(v):
        return str(v)[:4] if v else "?"

    lines = [f"F{i}: {t}" for i, (t, _) in enumerate(facts, 1)]
    raw = [v for _, vals in facts for v in vals]
    sec = []
    if stopped:
        sec.append("Comparable past trials that had stopped for poor enrollment (Jan 2017 record):")
        for r in stopped:
            why = (r.get("why_stopped_2017") or "").strip().replace("\n", " ")[:140]
            sec.append(f"- {r['nct_id']}: {str(r.get('title'))[:110]} | started {yr(r.get('start_date'))} | "
                       f"enrolled {r.get('enrollment')} | sites {r.get('n_sites_2017')} | stop reason: \"{why}\"")
            raw += [r.get("enrollment"), r.get("n_sites_2017")]
    if completed:
        sec.append("Completed comparable trials closest in size (Jan 2017 record):")
        for r in completed:
            sec.append(f"- {r['nct_id']}: {str(r.get('title'))[:110]} | started {yr(r.get('start_date'))} | "
                       f"enrolled {r.get('enrollment')} | sites {r.get('n_sites_2017')}")
            raw += [r.get("enrollment"), r.get("n_sites_2017")]
    if competing:
        sec.append("Largest competing trials recruiting on Jan 5, 2017 (by sites):")
        for r in competing:
            sec.append(f"- {r['nct_id']}: {str(r.get('title'))[:110]} | {r.get('phase')} | sites {r.get('n_sites_2017')}")
            raw += [r.get("n_sites_2017")]
    text = ("Evidence pack (ClinicalTrials.gov records as of Jan 5, 2017; numbers computed by code)\n\n"
            + "\n".join(lines) + ("\n\n" + "\n".join(sec) if sec else ""))
    allowed = {r["nct_id"] for r in stopped + completed + competing}
    if nct_id:
        allowed.discard(nct_id)
        assert nct_id not in text, "the audited trial's NCT ID must not reach the memo model"
    numbers = _numbers_in(text) | {float(v) for v in raw if isinstance(v, (int, float)) and not isinstance(v, bool)}
    fact_numbers = {f"F{i}": sorted(_numbers_in(t) | {float(v) for v in vals}) for i, (t, vals) in enumerate(facts, 1)}
    trial_numbers = {}
    for line in sec:
        m = NCT_RX.search(line)
        if m:
            trial_numbers[m.group(0)] = sorted(_numbers_in(line))
    return {"text": text, "fact_ids": [f"F{i}" for i in range(1, len(facts) + 1)],
            "allowed_nct_ids": sorted(allowed), "numbers": sorted(numbers),
            "fact_numbers": fact_numbers, "trial_numbers": trial_numbers}


def _numbers_in(text: str) -> set[float]:
    return {float(m.group(1).replace(",", "") + ("." + m.group(2) if m.group(2) else ""))
            for m in NUM_RX.finditer(NCT_RX.sub(" ", TAG_RX.sub(" ", text)))}


# ------------------------------------------------------------------------------- the check
def _number_ok(token: str, decimals: str | None, numbers: list[float]) -> bool:
    v = float(token.replace(",", "") + ("." + decimals if decimals else ""))
    d = len(decimals) if decimals else 0
    for a in numbers:
        for cand in (a, a * 100):
            if round(cand, d) == v or (d == 0 and math.floor(cand) == v):
                return True
    return False


def _check_text(s: str, ev: dict, rep: dict, scope: list[float] | None = None) -> str:
    allowed = set(ev["allowed_nct_ids"])

    def fix_id(m):
        rep["trial_ids"]["cited"] += 1
        if m.group(0) in allowed:
            rep["trial_ids"]["verified"] += 1
            return m.group(0)
        rep["trial_ids"]["removed"].append(m.group(0))
        return REMOVED_ID

    s = NCT_RX.sub(fix_id, s)

    def fix_tag(m):
        ids = [x.strip() for x in m.group(1).split(",")]
        good = [x for x in ids if x in ev["fact_ids"]]
        rep["fact_tags"]["cited"] += len(ids)
        rep["fact_tags"]["unknown"] += [x for x in ids if x not in ev["fact_ids"]]
        return f"[{', '.join(good)}]" if good else ""

    s = TAG_RX.sub(fix_tag, s)
    # numbers outside NCT IDs, fact tags and the removal markers
    protected = [(m.start(), m.end()) for rx in (NCT_RX, TAG_RX) for m in rx.finditer(s)]
    out, last = [], 0
    for m in NUM_RX.finditer(s):
        if any(a <= m.start() < b for a, b in protected):
            continue
        rep["numbers"]["checked"] += 1
        if _number_ok(m.group(1), m.group(2), ev["numbers"]):
            rep["numbers"]["verified"] += 1
            if scope is not None and not _number_ok(m.group(1), m.group(2), scope):
                rep["numbers"]["not_in_cited_facts"].append(m.group(0))
            continue
        rep["numbers"]["removed"].append(m.group(0))
        out.append(s[last:m.start()] + REMOVED_NUM)
        last = m.end()
    s = "".join(out) + s[last:]
    low = s.lower()
    rep["framing"] += [w for w in BANNED_FRAMING if re.search(r"\b" + re.escape(w) + r"\b", low)]
    return s


def _scope(b: dict, ev: dict) -> list[float]:
    """Numbers a bottleneck may use: those in the facts and trials it cites (tags, lists, inline IDs)."""
    blob = " ".join(str(b.get(k) or "") for k in BOTTLENECK_TEXT)
    fids = set(b.get("facts") or []) | {x.strip() for m in TAG_RX.finditer(blob) for x in m.group(1).split(",")}
    ncts = set(b.get("trials") or []) | set(NCT_RX.findall(blob))
    out = set()
    for f in fids:
        out |= set(ev.get("fact_numbers", {}).get(f, []))
    for t in ncts:
        out |= set(ev.get("trial_numbers", {}).get(t, []))
    return sorted(out) if ev.get("fact_numbers") else ev["numbers"]


def check_headline(headline: str, top: dict | None) -> dict:
    """The headline must state the top risk (share a number with bottleneck 1) and give no verdict."""
    problems = []
    verdicts = sorted({m.group(0).lower() for m in VERDICT_RX.finditer(headline or "")})
    if verdicts:
        problems.append("headline gives a verdict (" + ", ".join(verdicts) + ")")
    if top is not None:
        nums = lambda t: {m.group(0) for m in NUM_RX.finditer(NCT_RX.sub(" ", TAG_RX.sub(" ", t or "")))}
        if not nums(headline) & nums(top.get("evidence", "") + " " + top.get("title", "")):
            problems.append("headline does not state bottleneck 1's number")
    return {"verdict_words": verdicts, "problems": problems}


def check_memo(memo: dict, ev: dict) -> tuple[dict, dict]:
    """Verify every NCT ID, number and fact tag against the evidence pack."""
    rep = {"trial_ids": {"cited": 0, "verified": 0, "removed": []},
           "numbers": {"checked": 0, "verified": 0, "removed": [], "not_in_cited_facts": []},
           "fact_tags": {"cited": 0, "unknown": []}, "framing": [], "structure": []}
    clean = {k: _check_text(str(memo.get(k) or ""), ev, rep) for k in TEXT_KEYS}
    bns = memo.get("bottlenecks") if isinstance(memo.get("bottlenecks"), list) else []
    rep["trimmed"] = []
    if len(bns) > 5:  # the prompt asks for most important first, so code keeps the first 5
        rep["trimmed"] = [str((b or {}).get("title", ""))[:60] for b in bns[5:] if isinstance(b, dict)]
        bns = bns[:5]
    if len(bns) < 3:
        rep["structure"].append(f"only {len(bns)} bottlenecks (expected 3-5)")
    clean["bottlenecks"] = []
    for b in bns:
        if not isinstance(b, dict):
            continue
        cb = {k: _check_text(str(b.get(k) or ""), ev, rep, _scope(b, ev)) for k in BOTTLENECK_TEXT}
        cb["facts"] = [f for f in (b.get("facts") or []) if f in ev["fact_ids"]]
        cb["trials"] = [t for t in (b.get("trials") or []) if t in set(ev["allowed_nct_ids"])]
        bad = [t for t in (b.get("trials") or []) if t not in set(ev["allowed_nct_ids"])]
        rep["trial_ids"]["removed"] += bad
        rep["trial_ids"]["cited"] += len(b.get("trials") or [])
        rep["trial_ids"]["verified"] += len(cb["trials"])
        if not cb["facts"] and "[F" not in cb["evidence"]:
            rep["structure"].append(f"bottleneck '{cb['title'][:40]}' cites no fact")
        clean["bottlenecks"].append(cb)
    rep["framing"] = sorted(set(rep["framing"]))
    rep["headline"] = check_headline(clean["headline"], clean["bottlenecks"][0] if clean["bottlenecks"] else None)
    rep["passed"] = not (rep["trial_ids"]["removed"] or rep["numbers"]["removed"] or rep["fact_tags"]["unknown"]
                         or rep["framing"] or rep["structure"] or rep["headline"]["problems"])
    return clean, rep


def check_line(rep: dict) -> str:
    t, n = rep["trial_ids"], rep["numbers"]
    s = (f"Check: {t['verified']} of {t['cited']} trial ID citations verified"
         f"{', ' + str(len(t['removed'])) + ' removed' if t['removed'] else ''}; "
         f"{n['verified']} of {n['checked']} numbers found in the inputs"
         f"{', ' + str(len(n['removed'])) + ' removed' if n['removed'] else ''}")
    if n.get("not_in_cited_facts"):
        s += (f"; {len(n['not_in_cited_facts'])} number(s) appear in the inputs but not in the facts that "
              f"bottleneck cites ({', '.join(n['not_in_cited_facts'])}), flagged for review")
    if rep["fact_tags"]["unknown"]:
        s += f"; unknown fact tags dropped: {', '.join(rep['fact_tags']['unknown'])}"
    if rep["framing"]:
        s += f"; framing words flagged: {', '.join(rep['framing'])}"
    if rep["structure"]:
        s += f"; {'; '.join(rep['structure'])}"
    if rep.get("headline", {}).get("problems"):
        s += "; " + "; ".join(rep["headline"]["problems"])
    if rep.get("trimmed"):
        s += f"; {len(rep['trimmed'])} extra bottleneck(s) beyond 5 dropped by code"
    return s + (". All passed." if rep["passed"] else ".")


def render_markdown(memo: dict, rep: dict) -> str:
    out = ["## Feasibility memo for the sponsor", "", memo.get("headline", ""), ""]
    for i, b in enumerate(memo.get("bottlenecks") or [], 1):
        out += [f"**{i}. {b['title']}**", "", b["evidence"], "", f"*What to check:* {b['what_to_check']}", ""]
    if memo.get("evidence_limits"):
        out += [f"*Limits of this evidence:* {memo['evidence_limits']}", ""]
    out += [f"> {check_line(rep)}", "",
            "_Study-planning memo for trial sponsors, not medical advice. Written by Muse Wonder from the "
            "trial card, the search trace and code-computed numbers (ClinicalTrials.gov records as of "
            "Jan 5, 2017); every trial ID and number was checked by code against those inputs._"]
    return "\n".join(out)


# ------------------------------------------------------------------------------ the model
def cost_usd(usage: dict | None, model: str = MODEL) -> float:
    if not usage:
        return 0.0
    pin, pout = PRICES.get(model, PRICES[MODEL])
    return round(usage.get("prompt_tokens", 0) * pin + usage.get("completion_tokens", 0) * pout, 6)


def _client():
    from openai import OpenAI
    key = os.environ.get("META_API_KEY")
    if not key:
        raise MemoError("META_API_KEY is not set in the environment")
    return OpenAI(base_url=BASE_URL, api_key=key, timeout=300, max_retries=0)


def write_memo(card: dict, audit: dict, pools_dir=None, nct_id: str | None = None, pages: dict | None = None,
               card_flags: list | None = None, model: str = MODEL, reasoning_effort: str = "medium",
               client=None, raw_path: Path | None = None) -> dict:
    ev = build_evidence(card, audit, pools_dir, nct_id, pages, card_flags)
    client = client or _client()
    t0 = time.time()
    try:
        resp = client.chat.completions.create(
            model=model, reasoning_effort=reasoning_effort, max_completion_tokens=12000,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": PROMPT.read_text()},
                      {"role": "user", "content": ev["text"]}])
    except Exception as e:  # noqa: BLE001 - surfaced to the caller with the API's own message
        raise MemoError(f"{type(e).__name__}: {getattr(e, 'status_code', '')} {str(e)[:400]}") from e
    latency = round(time.time() - t0, 1)
    d = resp.model_dump()
    if raw_path:
        Path(raw_path).write_text(json.dumps({"request_text": ev["text"], "latency_s": latency,
                                               "response": d}, default=str))
    content = resp.choices[0].message.content or ""
    m = re.search(r"\{.*\}", content, re.S)
    try:
        memo = json.loads(m.group(0)) if m else None
    except json.JSONDecodeError:
        memo = None
    usage = d.get("usage") or {}
    if not isinstance(memo, dict):
        raise MemoError(f"memo reply was not JSON (finish_reason={d['choices'][0].get('finish_reason')}, "
                        f"{usage.get('completion_tokens')} completion tokens)")
    clean, rep = check_memo(memo, ev)
    return {"memo": clean, "markdown": render_markdown(clean, rep), "check": rep, "model": model,
            "reasoning_effort": reasoning_effort, "usage": usage, "cost_usd": cost_usd(usage, model),
            "latency_s": latency, "evidence": ev, "model_memo": memo}
