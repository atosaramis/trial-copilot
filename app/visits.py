"""Count visits from the visit schedule that Muse Spark reads off the schedule pages.

The model does not count. It writes the schedule down as periods and visit days
(see prompts/visit_schedule_vision.txt), and this code lays the visits out on a
study-day line and counts them. That keeps the numbers stable when oncology cycles
repeat with no fixed end.

Conventions (build spec section 12):
- Day 1 is randomization or the first dose. Week n means study day 7n + 1.
- The 26-week window is study days 1 to 183 (through the nominal week-26 visit);
  the 12-week window is study days 1 to 85. Screening (before day 1) is counted separately.
- Counts are for one participant who stays on study treatment through week 26, so
  end-of-treatment, early-termination, unscheduled and "as needed" visits are not counted.
- visits_open_ended is true when treatment cycles repeat until progression or another stop
  event (follow-up contacts that run "until death" do not count).
- A visit is one study day with a scheduled contact. Two contacts on the same day count once;
  if either is at the clinic, the day is a clinic visit.
- "clinic" means the participant travels to the site. "phone", "video" and "home" visits are
  remote and are reported separately; burden uses clinic visits.
- A protocol-required surgery is a major procedure, not a clinic visit. It still sits on the
  timeline (later visits may be timed from it) but is never counted; it is reported as a flag
  with its study day and any stated inpatient days. Pre-op and post-op assessment visits count.
- Invasive procedures (biopsies, marrow samples, etc.) are counted by purpose: standard of care
  vs research only, mandated occurrences on study days up to 183, screening included.
- The pre-registered sensitivity definition (original wording) counts every contact, clinic or
  remote, from screening through study day 85.
"""
from __future__ import annotations

import re

WINDOW_26W = 183
WINDOW_12W = 85
CLINIC = "clinic"
REMOTE_TYPES = ("phone", "video", "home", "remote")
_CONTACT_SYNONYMS = {
    "clinic": CLINIC, "site": CLINIC, "in-person": CLINIC, "in person": CLINIC, "office": CLINIC,
    "hospital": CLINIC, "inpatient": CLINIC, "outpatient": CLINIC,
    "phone": "phone", "telephone": "phone", "call": "phone", "phone call": "phone",
    "telephone call": "phone",
    "video": "video", "telemedicine": "video", "televisit": "video", "virtual": "video",
    "home": "home", "home visit": "home", "home nurse": "home",
    "remote": "remote",
}


def _int(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        return int(round(float(str(v).replace(",", "").strip())))
    except ValueError:
        return None


def contact_type(v) -> str:
    s = str(v or "clinic").strip().lower()
    if s in _CONTACT_SYNONYMS:
        return _CONTACT_SYNONYMS[s]
    for k, t in _CONTACT_SYNONYMS.items():
        if k in s:
            return t
    return CLINIC


def _visit_day(v: dict):
    """Day within the cycle (cyclic periods) or study day (other periods).

    Periods hold only visits on or after Day 1, so a "Day 0" there (a protocol that calls
    randomization Day 0, or "Week 0" written as day 0) is read as Day 1.
    """
    d = _int(v.get("day"))
    if d is None and v.get("week") is not None:
        w = _int(v.get("week"))
        d = None if w is None else 7 * w + 1
    if d == 0:
        d = 1
    return d


_SURGERY = re.compile(r"\b(surgery|surgical resection|resection|operation|lobectomy|pneumonectomy|"
                      r"mastectomy|lumpectomy|cystectomy|prostatectomy|transplant(ation)?)\b", re.I)
_SURGERY_VISIT = re.compile(r"\b(pre[- ]?op|post[- ]?op|pre[- ]?surg|post[- ]?surg|follow|assessment|"
                            r"evaluation|visit|recovery)", re.I)


def is_major_procedure(v: dict) -> bool:
    """A surgery entry on the schedule (not a pre-op or post-op assessment visit)."""
    if str(v.get("kind") or "").lower() == "major_procedure":
        return True
    label = str(v.get("label") or "")
    return bool(_SURGERY.search(label)) and not _SURGERY_VISIT.search(label)


def _note_estimated(v: dict, out: dict):
    if v.get("day_estimated"):
        out["notes"].append(f"visit '{str(v.get('label'))[:30]}' timing estimated from a window")


def layout(schedule: dict | None, horizon: int = WINDOW_26W) -> dict:
    """Place every scheduled visit on the study-day line, up to `horizon`.

    Returns {"days": {study_day: contact}, "screening": [contact, ...],
             "open_ended": bool, "notes": [...]}.
    """
    out = {"days": {}, "screening": [], "open_ended": False, "notes": [], "major": [],
           "cycle_starts": {}}
    if not isinstance(schedule, dict):
        return out
    days: dict[int, str] = {}

    def add(day: int, contact: str, v: dict | None = None):
        if v is not None and is_major_procedure(v):
            if not any(m["label"] == v.get("label") and m["day"] == day for m in out["major"]):
                out["major"].append({"label": str(v.get("label") or "")[:60], "day": day,
                                     "inpatient_days": _int(v.get("inpatient_days")),
                                     "conditional": bool(v.get("conditional")),
                                     "day_estimated": bool(v.get("day_estimated"))})
            return
        if day < 1:
            out["screening"].append(contact)
            return
        if day > horizon:
            return
        if days.get(day) != CLINIC:
            days[day] = contact

    for v in schedule.get("screening_visits") or []:
        if isinstance(v, dict) and not v.get("conditional") and not is_major_procedure(v):
            out["screening"].append(contact_type(v.get("contact")))

    cursor = 1  # study day on which the next cyclic period starts
    for p in schedule.get("periods") or []:
        if not isinstance(p, dict):
            continue
        # Conditional visits are not counted, but a surgery stays on the timeline either way.
        visits = [v for v in (p.get("visits") or [])
                  if isinstance(v, dict) and (not v.get("conditional") or is_major_procedure(v))]
        length = _int(p.get("cycle_length_days"))
        if length and length > 0:
            n = _int(p.get("n_cycles"))
            if p.get("repeats_until_stop") or n is None:
                out["open_ended"] = True
                n = None
            first = _int(p.get("first_cycle"))
            k = 0
            while (n is None or k < n) and cursor <= horizon:
                cycle_no = first + k if first is not None else None
                if cycle_no is not None:
                    out["cycle_starts"].setdefault(cycle_no, cursor)
                for v in visits:
                    only = v.get("only_in_cycles")
                    if only and cycle_no is not None and cycle_no not in {_int(x) for x in only}:
                        continue
                    d = _visit_day(v)
                    if d is not None:
                        if k == 0:
                            _note_estimated(v, out)
                        add(cursor + d - 1, contact_type(v.get("contact")), v)
                cursor += length
                k += 1
            if n is None:
                break  # open-ended period: nothing after it falls in the window
        else:
            # Non-cyclic period: listed visit days, optionally "then every N days".
            # day_reference "period_start" means day 1 is the first day after the previous period.
            offset = cursor - 1 if p.get("day_reference") == "period_start" else 0
            every = _int(p.get("repeat_every_days"))
            last_day = None
            for v in visits:
                d = _visit_day(v)
                if d is None:
                    out["notes"].append(f"visit '{str(v.get('label'))[:30]}' has no day, skipped")
                    continue
                _note_estimated(v, out)
                add(d + offset, contact_type(v.get("contact")), v)
                last_day = d + offset if last_day is None else max(last_day, d + offset)
            if every and every > 0:
                until = _int(p.get("repeat_until_day"))
                stop_driven = bool(p.get("repeats_until_stop"))
                if until is None and stop_driven:
                    pass  # follow-up that runs until a stop event; "open-ended" is about treatment cycles
                elif until is None:
                    # No end and not stop-driven: read it as one contact `every` days later.
                    until = (last_day if last_day is not None else cursor - 1) + every
                    out["notes"].append(f"period '{str(p.get('label'))[:30]}' repeat has no end, counted once")
                else:
                    until += offset
                plain = [v for v in visits if not is_major_procedure(v)]
                contact = contact_type(plain[-1].get("contact") if plain else p.get("contact"))
                c = (last_day if last_day is not None else cursor - 1) + every
                while c <= horizon and (until is None or c <= until):
                    add(c, contact)
                    c += every
                if until is None:
                    break  # stop-driven: nothing after it falls in the window
                last_day = max(last_day or 0, until)
            if last_day is not None:
                cursor = max(cursor, last_day + 1)
    out["days"] = dict(sorted(days.items()))
    return out


# Wording that makes a procedure recommended or optional rather than required (Day 2 fix:
# "highly recommended" mediastinoscopy in NCT01857271 was once read as mandatory).
NOT_MANDATED_WORDING = re.compile(
    r"recommend|optional|encourag|prefer|discretion|if (clinically )?(indicated|available|feasible|possible)"
    r"|as (clinically )?indicated|when (clinically )?indicated|consent|where available|may (be|undergo)"
    r"|should be considered|suggested", re.I)


def procedure_is_mandated(p: dict) -> bool:
    """Mandated = the model marked it mandatory AND its quoted wording is not a recommendation.

    Code has the last word: "highly recommended", "optional", "if clinically indicated" etc.
    are never mandated, whatever the model's mandatory flag says.
    """
    if not isinstance(p, dict) or p.get("mandatory") is not True:
        return False
    wording = str(p.get("requirement_wording") or "")
    return not NOT_MANDATED_WORDING.search(wording)


_SCREEN_WEEK = re.compile(r"\b(?:w|wk|week)\s*(-\s*\d+)", re.I)
_SCREEN_DAY = re.compile(r"\b(?:d|day)\s*(-\s*\d+)", re.I)


def screening_window_from_visits(screening_visits) -> int | None:
    """Days from the first screening visit to Day 1, from the visits' own timing.

    Uses each visit's "day" (negative) or "week" (negative; week -4 = 28 days), or a label such
    as "V1 (w-4)" or "Day -28 to -1". Returns the largest, or None when no timing is shown.
    Week -n counts as n*7 days, the way protocols state the window.
    """
    best = None
    for v in screening_visits or []:
        if not isinstance(v, dict):
            continue
        cands = []
        d, w = _int(v.get("day")), _int(v.get("week"))
        if d is not None and d < 0:
            cands.append(-d)
        if w is not None and w < 0:
            cands.append(-7 * w)
        label = str(v.get("label") or "")
        for m in _SCREEN_WEEK.finditer(label):
            cands.append(-7 * int(m.group(1).replace(" ", "")))
        for m in _SCREEN_DAY.finditer(label):
            cands.append(-int(m.group(1).replace(" ", "")))
        for c in cands:
            if c > 0 and (best is None or c > best):
                best = c
    return best


def _occurrence_day(o, lay: dict):
    """Study day of one procedure occurrence: {"study_day": d} or {"cycle": c, "day": d}."""
    if not isinstance(o, dict):
        return None
    if o.get("screening"):
        return 0
    sd = _int(o.get("study_day"))
    if sd is not None:
        return sd
    if o.get("week") is not None and _int(o.get("week")) is not None:
        return 7 * _int(o.get("week")) + 1
    c, d = _int(o.get("cycle")), _int(o.get("day"))
    if c is not None:
        start = lay["cycle_starts"].get(c)
        if start is None and lay["cycle_starts"]:
            # Cycle beyond the laid-out window, or numbering we did not see.
            return WINDOW_26W + 1 if c > max(lay["cycle_starts"]) else None
        return None if start is None else start + (d or 1) - 1
    return None


def count_procedures(procs, lay: dict, window: int = WINDOW_26W) -> dict:
    """Mandated invasive-procedure occurrences up to `window`, split by purpose."""
    res = {"standard_of_care": 0, "research_only": 0, "unplaced": [], "research_mandatory": False}
    for p in procs or []:
        if not procedure_is_mandated(p):
            continue
        purpose = "research_only" if str(p.get("purpose") or "").lower().startswith("research") \
            else "standard_of_care"
        if purpose == "research_only":
            res["research_mandatory"] = True
        days = []
        for o in p.get("occurrences") or []:
            d = _occurrence_day(o, lay)
            if d is None:
                res["unplaced"].append(str(p.get("name"))[:40])
            else:
                days.append(d)
        every = _int(p.get("then_every_days"))
        if every and every > 0 and days:
            until = _int(p.get("repeat_until_day"))
            c = max(days) + every
            while c <= window and (until is None or c <= until):
                days.append(c)
                c += every
        res[purpose] += sum(1 for d in set(days) if d <= window)
    return res


def count_visits(schedule: dict | None, procedures=None) -> dict:
    """The visit and procedure fields that code puts on the card."""
    lay = layout(schedule, WINDOW_26W)
    days = lay["days"]

    def n(window, clinic):
        return sum(1 for d, c in days.items() if d <= window and ((c == CLINIC) == clinic))

    has_schedule = bool(days) or bool(lay["screening"])
    res = {
        "clinic_visits_first_26_weeks": n(WINDOW_26W, True) if has_schedule else None,
        "remote_visits_first_26_weeks": n(WINDOW_26W, False) if has_schedule else None,
        "clinic_visits_first_12_weeks": n(WINDOW_12W, True) if has_schedule else None,
        "remote_visits_first_12_weeks": n(WINDOW_12W, False) if has_schedule else None,
        "screening_clinic_visits": (sum(1 for c in lay["screening"] if c == CLINIC)
                                    if has_schedule else None),
        "visits_open_ended": lay["open_ended"] if has_schedule else None,
        # Pre-registered sensitivity definition (original wording): every contact, clinic or
        # remote, from screening through study day 85.
        "contacts_screening_to_week_12": (len(lay["screening"]) + sum(1 for d in days if d <= WINDOW_12W)
                                          if has_schedule else None),
        "visit_days_first_26_weeks": [[d, c] for d, c in days.items()],
        "notes": lay["notes"],
    }
    major = [m for m in lay["major"] if not m["conditional"]]
    res["major_procedure_required"] = bool(major) if has_schedule else None
    res["major_procedure_day"] = major[0]["day"] if major else None
    stays = [m["inpatient_days"] for m in major if m["inpatient_days"] is not None]
    res["major_procedure_inpatient_days"] = sum(stays) if stays else None
    res["major_procedures"] = lay["major"]
    if procedures is not None:
        pc = count_procedures(procedures, lay)
        res["soc_invasive_procedures_first_26_weeks"] = pc["standard_of_care"]
        res["research_invasive_procedures_first_26_weeks"] = pc["research_only"]
        res["mandatory_fresh_biopsy"] = pc["research_mandatory"]
        res["notes"] += [f"procedure '{n}' has an occurrence with no placeable day" for n in pc["unplaced"]]
    else:
        res["soc_invasive_procedures_first_26_weeks"] = None
        res["research_invasive_procedures_first_26_weeks"] = None
        res["mandatory_fresh_biopsy"] = None
    if has_schedule:
        res["visit_count_basis"] = (
            f"Code count, study days 1-183, one participant on treatment throughout: "
            f"{res['clinic_visits_first_26_weeks']} clinic and {res['remote_visits_first_26_weeks']} "
            f"remote visit days; screening counted separately"
            + ("; cycles repeat until a stop event" if lay["open_ended"] else "") + ".")
    else:
        res["visit_count_basis"] = None
    return res
