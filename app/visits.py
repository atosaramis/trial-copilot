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
"""
from __future__ import annotations

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
    """Day within the cycle (cyclic periods) or study day (other periods)."""
    d = _int(v.get("day"))
    if d is None and v.get("week") is not None:
        w = _int(v.get("week"))
        d = None if w is None else 7 * w + 1
    return d


def _note_estimated(v: dict, out: dict):
    if v.get("day_estimated"):
        out["notes"].append(f"visit '{str(v.get('label'))[:30]}' timing estimated from a window")


def layout(schedule: dict | None, horizon: int = WINDOW_26W) -> dict:
    """Place every scheduled visit on the study-day line, up to `horizon`.

    Returns {"days": {study_day: contact}, "screening": [contact, ...],
             "open_ended": bool, "notes": [...]}.
    """
    out = {"days": {}, "screening": [], "open_ended": False, "notes": []}
    if not isinstance(schedule, dict):
        return out
    days: dict[int, str] = {}

    def add(day: int, contact: str):
        if day < 1:
            out["screening"].append(contact)
            return
        if day > horizon:
            return
        if days.get(day) != CLINIC:
            days[day] = contact

    for v in schedule.get("screening_visits") or []:
        if isinstance(v, dict) and not v.get("conditional"):
            out["screening"].append(contact_type(v.get("contact")))

    cursor = 1  # study day on which the next cyclic period starts
    for p in schedule.get("periods") or []:
        if not isinstance(p, dict):
            continue
        visits = [v for v in (p.get("visits") or []) if isinstance(v, dict) and not v.get("conditional")]
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
                for v in visits:
                    only = v.get("only_in_cycles")
                    if only and cycle_no is not None and cycle_no not in {_int(x) for x in only}:
                        continue
                    d = _visit_day(v)
                    if d is not None:
                        if k == 0:
                            _note_estimated(v, out)
                        add(cursor + d - 1, contact_type(v.get("contact")))
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
                add(d + offset, contact_type(v.get("contact")))
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
                contact = contact_type(visits[-1].get("contact") if visits else p.get("contact"))
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


def count_visits(schedule: dict | None) -> dict:
    """The visit fields that code puts on the card."""
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
        "visit_days_first_26_weeks": [[d, c] for d, c in days.items()],
        "notes": lay["notes"],
    }
    if has_schedule:
        res["visit_count_basis"] = (
            f"Code count, study days 1-183, one participant on treatment throughout: "
            f"{res['clinic_visits_first_26_weeks']} clinic and {res['remote_visits_first_26_weeks']} "
            f"remote visit days; screening counted separately"
            + ("; cycles repeat until a stop event" if lay["open_ended"] else "") + ".")
    else:
        res["visit_count_basis"] = None
    return res
