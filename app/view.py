"""Turns saved or live results into what the templates show. Display only: no model calls,
and no number is computed here except formatting (the risk numbers come from app/risk.py)."""
from __future__ import annotations

import json
from pathlib import Path

from .memo import POINTS_HEADING, check_line

BACKTEST = Path(__file__).resolve().parents[1] / "backtest"
UNIVARIATE = [("comp_rate", "Comparable-trial poor-enrollment stop rate"), ("pace", "Enrollment pace needed per site"),
              ("biomarker", "Required biomarker"), ("visits", "Clinic visits, study days 1-85"),
              ("visits_sensitivity", "All contacts to day 85 (sensitivity)")]
AGREE = [("phase", "Phase"), ("randomized", "Randomized"), ("open_label", "Open label"), ("n_arms", "Number of arms"),
         ("enrollment", "Planned enrollment (within 10%)"), ("sites", "Sites (within 20%)")]

CARD_GROUPS = [
    ("Design", [("condition", "Condition"), ("interventions", "Study drugs"), ("phase", "Phase"),
                ("n_arms", "Arms"), ("allocation", "Allocation"), ("masking", "Masking"),
                ("placebo_arm", "Placebo arm"), ("sponsor_type", "Sponsor type")]),
    ("Enrollment and sites", [("planned_enrollment", "Planned enrollment"), ("planned_sites", "Planned sites"),
                              ("planned_countries", "Planned countries"),
                              ("enrollment_period_months", "Enrollment period (months)")]),
    ("Eligibility", [("age_criterion", "Age criterion (quoted)"), ("min_age_years", "Minimum age"),
                     ("max_age_years", "Maximum age"), ("required_biomarker", "Required biomarker"),
                     ("max_prior_lines", "Prior therapy"), ("washout_days_max", "Longest washout (days)"),
                     ("performance_status_requirement", "Performance status"),
                     ("brain_mets_allowed", "Brain metastases")]),
]
VISIT_FIELDS = [
    ("clinic_visits_first_26_weeks", "Clinic visits, first 26 weeks"),
    ("remote_visits_first_26_weeks", "Remote visits, first 26 weeks"),
    ("clinic_visits_first_12_weeks", "Clinic visits, first 12 weeks"),
    ("remote_visits_first_12_weeks", "Remote visits, first 12 weeks"),
    ("screening_clinic_visits", "Screening clinic visits"),
    ("screening_window_days", "Screening window (days)"),
    ("visits_open_ended", "Treatment cycles open-ended"),
    ("contacts_screening_to_week_12", "All contacts, screening to week 12 (sensitivity)"),
    ("soc_invasive_procedures_first_26_weeks", "Mandated invasive procedures, standard of care"),
    ("research_invasive_procedures_first_26_weeks", "Mandated invasive procedures, research only"),
    ("mandatory_fresh_biopsy", "Mandatory research biopsy"),
    ("inpatient_stay_required", "Inpatient stay required"),
    ("major_procedure_required", "Protocol-required surgery"),
    ("major_procedure_day", "Surgery study day"),
]
PAGE_KEY = {"min_age_years": "age_criterion", "max_age_years": "age_criterion",
            "clinic_visits_first_26_weeks": "visit_schedule", "remote_visits_first_26_weeks": "visit_schedule",
            "clinic_visits_first_12_weeks": "visit_schedule", "remote_visits_first_12_weeks": "visit_schedule",
            "screening_clinic_visits": "visit_schedule", "visits_open_ended": "visit_schedule",
            "contacts_screening_to_week_12": "visit_schedule",
            "soc_invasive_procedures_first_26_weeks": "invasive_procedures",
            "research_invasive_procedures_first_26_weeks": "invasive_procedures",
            "mandatory_fresh_biopsy": "invasive_procedures", "major_procedure_day": "major_procedure_required"}
TOOL_LABEL = {"search_comparable_trials": "search_comparable_trials", "count_competing_trials": "count_competing_trials",
              "get_trial": "get_trial"}


def fmt(v):
    if v is None or v == "" or v == []:
        return "not stated"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, list):
        return ", ".join(fmt(x) for x in v)
    if isinstance(v, float):
        return f"{v:g}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def pct(x, nd=1):
    return "–" if x is None else f"{100 * x:.{nd}f}%"


def _when(occ: list) -> str:
    out = []
    for o in occ:
        if o.get("screening"):
            out.append("screening")
        elif o.get("cycle") is not None:
            out.append(f"C{o['cycle']}D{o.get('day', 1)}")
        elif o.get("day") is not None:
            out.append(f"day {o['day']}")
        elif o.get("week") is not None:
            out.append(f"week {o['week']}")
    return ", ".join(out) or "–"


def step_view(st: dict) -> dict:
    args = {k: v for k, v in (st.get("args") or {}).items() if v not in (None, [], "")}
    return {"n": st.get("step"), "tool": st.get("tool"), "args": args, "rows": st.get("rows"),
            "outcomes": st.get("outcome_counts_2017"), "reason": (st.get("reason") or "").strip(),
            "status": st.get("status"), "result_id": st.get("result_id"),
            "latency": st.get("tool_latency_s")}


def _fields(card, pages, spec):
    return [{"key": k, "label": lab, "value": fmt(card.get(k)), "pages": pages.get(PAGE_KEY.get(k, k)) or []}
            for k, lab in spec]


def full_context(d: dict) -> dict:
    cardw = d.get("card") or {}
    card, pages = cardw.get("card") or {}, cardw.get("_pages") or {}
    audit = d.get("audit") or {}
    search, risk = audit.get("search") or {}, audit.get("risk") or {}
    sp = risk.get("site_pace") or {}
    sm = risk.get("slider_model") or {}
    memo = d.get("memo")
    procs = [{"name": p.get("name"), "purpose": (p.get("purpose") or "").replace("_", " "),
              "mandatory": p.get("mandatory"), "when": _when(p.get("occurrences") or []),
              "wording": p.get("requirement_wording"), "decided_by": p.get("decided_by")}
             for p in card.get("invasive_procedures") or []]
    sched_pages = pages.get("visit_schedule") or card.get("schedule_of_assessments_pages") or []
    ctx = {
        "nct": d.get("nct_id"), "label": d.get("label"), "title": d.get("registry_title_2017"),
        "sha": d.get("pdf_sha256"), "n_pages": d.get("pdf_pages"),
        "page_url": (lambda n: f"{d['protocol_url']}#page={n}") if d.get("protocol_url")
        else (lambda n: f"/pdf/{d.get('pdf_sha256')}#page={n}"),
        "groups": [(g, _fields(card, pages, spec)) for g, spec in CARD_GROUPS],
        "visit_fields": _fields(card, pages, VISIT_FIELDS),
        "procedures": procs, "schedule_pages": sched_pages[:8],
        "card_flags": cardw.get("flags") or [],
        "steps": [step_view(s) for s in search.get("steps") or []],
        "search": {"used": search.get("tool_calls_used"), "max": search.get("max_steps", 6),
                   "capped": search.get("capped"), "comparable": search.get("comparable_search"),
                   "competing": search.get("competing_search"), "summary": search.get("summary"),
                   "latency": search.get("latency_s"), "cost": search.get("cost_usd"),
                   "model": search.get("model"), "effort": search.get("reasoning_effort"),
                   "flags": search.get("flags") or []},
        "rr": audit.get("registry_risk"),
        "risk": risk, "sp": sp, "comp": risk.get("comparable_trials"), "pool": risk.get("all_trials_in_pool"),
        "competing": risk.get("competing_trials"), "risk_flags": risk.get("flags") or [],
        "slider": {"planned": sm.get("planned_enrollment") or sp.get("planned_enrollment"),
                   "sites": sm.get("sites") or sp.get("sites"), "months": sm.get("months") or sp.get("months"),
                   "offset": sm.get("months_basis_offset") or 0.0, "q": sm.get("pace_quantiles") or [],
                   "registry_sites": sp.get("registry_sites_2017")},
        "memo": memo, "check_line": check_line(memo["check"]) if memo else None,
        "is_demo": bool(d.get("nct_id")),
    }
    return ctx


def validation_context() -> dict | None:
    """Saved backtest aggregates for Tab 2 (no computation beyond picking fields)."""
    try:
        t = json.loads((BACKTEST / "tuning_summary.json").read_text())
        h = json.loads((BACKTEST / "heldout_summary.json").read_text())
    except (OSError, ValueError):
        return None
    ag = t["extraction_agreement_with_2017_registry"]
    return {
        "t": t, "h": h,
        "univariate": [(lab, t["univariate"][k]["imputed_all"]) for k, lab in UNIVARIATE],
        "agreement": [(lab, ag["original"][k], ag["amended"][k]) for k, lab in AGREE],
        "n_original": ag["original"]["n_trials"], "n_amended": ag["amended"]["n_trials"],
        "bins": h["primary"]["B"]["calibration"]["bins_10"],
    }


GLOBALS = {"pct": pct, "fmt": fmt, "points_heading": POINTS_HEADING}
FILTERS = {"pct": pct, "fmt": fmt}
