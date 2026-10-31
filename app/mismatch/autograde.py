"""Grade each mismatch against later registry versions (Jan 2020 and Jan 2023 AACT snapshots).

Deterministic, no model calls. Categories describe what the public record did, never intent:

- caught_up         the registry later reached the protocol value: it was lagging
                    (rules v2 also counted passing the protocol value as caught up)
- registry_exceeded_protocol  (rules v3) the registry later moved past the protocol value and
                    beyond tolerance, e.g. 5 -> 50 sites against a plan of 20: the documents still disagree
- partly_caught_up  the registry moved toward the protocol value but stayed short
- never_changed     the registry kept its Jan 2017 value
- changed_other_way the registry changed, but not toward the protocol value
- ambiguous         we cannot settle it from the record: our reading is doubtful, the later record
                    is missing, or (enrollment) the trial finished and only an actual count remains

Only design fields are read from the later snapshots (sites, countries, enrollment, phase,
allocation, arms). Trial status and stop reasons are never loaded here.

Rule versions (pass `rules=` to `grade`): "v2" reproduces the first scan; "v3" (default) adds
registry_exceeded_protocol.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .finder import (Mismatch, card_randomized, enrollment_tolerance, normalize_phase, registry_randomized,
                     site_tolerance)

CATEGORIES = ("caught_up", "partly_caught_up", "registry_exceeded_protocol", "never_changed", "changed_other_way",
              "ambiguous")
RULES = ("v2", "v3")
DEFAULT_RULES = "v3"
SETTLED = set(CATEGORIES) - {"ambiguous"}


@dataclass(frozen=True)
class Snapshot:
    date: str                 # e.g. "2020-01-01"
    n_sites: float | None = None
    n_countries: float | None = None
    enrollment: float | None = None
    enrollment_type: str | None = None   # Anticipated | Actual
    phase: str | None = None
    allocation: str | None = None
    n_arms: float | None = None


@dataclass(frozen=True)
class Grade:
    category: str
    reason: str
    later: tuple[tuple[str, object], ...] = ()   # (snapshot date, value) used for the grade

    @property
    def settled(self) -> bool:
        return self.category in SETTLED


def _tol(field: str, p: float) -> float:
    return {"sites": site_tolerance(p), "enrollment": enrollment_tolerance(p)}.get(field, 0.0)


def _value(field: str, s: Snapshot):
    return {"sites": s.n_sites, "countries": s.n_countries, "enrollment": s.enrollment, "arms": s.n_arms,
            "phase": s.phase, "randomized": s.allocation}[field]


def _grade_numeric(m: Mismatch, later: list[tuple[str, float]], rules: str = "v2") -> tuple[str, str]:
    p, r0 = float(m.protocol_value), float(m.registry_value)
    tp, t0 = _tol(m.field, p), _tol(m.field, r0)
    if rules != "v2":
        for d, v in later:
            if abs(v - p) <= tp:
                return "caught_up", f"registry reached the protocol value by {d}"
        for d, v in later:
            if (v - p) * (r0 - p) < 0:
                return "registry_exceeded_protocol", f"registry moved past the protocol value by {d} ({v:g} vs {p:g})"
    for d, v in later:
        if abs(v - p) <= tp:
            return "caught_up", f"registry reached the protocol value by {d}"
        if (v - p) * (r0 - p) < 0:
            return "caught_up", f"registry passed the protocol value by {d}"
    if all(abs(v - r0) <= t0 for _, v in later):
        return "never_changed", "registry kept its 2017 value"
    best = min(later, key=lambda dv: abs(dv[1] - p))
    if abs(best[1] - p) < abs(r0 - p):
        return "partly_caught_up", f"registry moved toward the protocol value by {best[0]} but stayed short"
    return "changed_other_way", "registry changed, but away from the protocol value"


def grade(m: Mismatch, snapshots: list[Snapshot], rules: str = DEFAULT_RULES) -> Grade:
    if rules not in RULES:
        raise ValueError(f"unknown rules {rules!r}")
    snaps = sorted(snapshots, key=lambda s: s.date)
    if "protocol_inconsistent" in m.traps:
        later = tuple((s.date, s.enrollment) for s in snaps if s.enrollment is not None)
        return Grade("ambiguous", "the protocol states different planned totals; nothing to grade against", later)
    if m.field == "enrollment":
        # Only an anticipated (planned) number can show the plan was corrected.
        plan = [(s.date, s.enrollment) for s in snaps if s.enrollment is not None
                and str(s.enrollment_type or "").lower() == "anticipated"]
        actual = [(s.date, s.enrollment) for s in snaps if s.enrollment is not None
                  and str(s.enrollment_type or "").lower() == "actual"]
        if not plan:
            if actual:
                d, v = actual[0]
                closer = "protocol" if abs(v - float(m.protocol_value)) < abs(v - float(m.registry_value)) else "registry"
                return Grade("ambiguous", f"trial finished before the next snapshot; actual enrollment {v:g} "
                                          f"is closer to the {closer} value", tuple(actual))
            return Grade("ambiguous", "no later registry record")
        later = plan
    else:
        later = [(s.date, _value(m.field, s)) for s in snaps if _value(m.field, s) not in (None, "")]
    if not later:
        return Grade("ambiguous", "no later registry record")
    if m.field in ("phase", "randomized"):
        norm = normalize_phase if m.field == "phase" else registry_randomized
        pv = normalize_phase(m.protocol_value) if m.field == "phase" else card_randomized(m.protocol_value)
        r0 = norm(m.registry_value)
        cat, why = "never_changed", "registry kept its 2017 value"
        for d, v in later:
            if norm(v) == pv:
                cat, why = "caught_up", f"registry matched the protocol by {d}"
                break
            if norm(v) != r0:
                cat, why = "changed_other_way", "registry changed, but not to the protocol value"
    else:
        cat, why = _grade_numeric(m, [(d, float(v)) for d, v in later], rules)
    if cat != "caught_up" and m.doubtful_reading:
        traps = ", ".join(t for t in m.traps if t != "registry_placeholder")
        return Grade("ambiguous", f"our protocol reading is doubtful ({traps}); record alone: {cat}", tuple(later))
    return Grade(cat, why, tuple(later))


# ---------- loading AACT flat-file snapshots (pipe-delimited) ----------

def _read(path: Path, ids: set[str], cols: list[str]):
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        rd = csv.DictReader(f, delimiter="|", quoting=csv.QUOTE_NONE)
        for row in rd:
            if row.get("nct_id") in ids:
                yield {c: row.get(c) for c in ["nct_id", *cols]}


def _f(v):
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def load_snapshot(directory: str | Path, date: str, nct_ids) -> dict[str, Snapshot]:
    """Design fields for `nct_ids` from one AACT flat-file snapshot directory."""
    d, ids = Path(directory), set(nct_ids)
    st = {r["nct_id"]: r for r in _read(d / "studies.txt", ids, ["phase", "enrollment", "enrollment_type",
                                                                  "number_of_arms"])}
    cv = {r["nct_id"]: r for r in _read(d / "calculated_values.txt", ids, ["number_of_facilities"])}
    de = {r["nct_id"]: r for r in _read(d / "designs.txt", ids, ["allocation"])}
    co: dict[str, int] = {}
    for r in _read(d / "countries.txt", ids, ["removed"]):
        if str(r["removed"]).lower() not in ("t", "true"):
            co[r["nct_id"]] = co.get(r["nct_id"], 0) + 1
    out = {}
    for n in ids & (set(st) | set(cv)):
        s = st.get(n, {})
        out[n] = Snapshot(date, _f(cv.get(n, {}).get("number_of_facilities")), float(co[n]) if n in co else None,
                          _f(s.get("enrollment")), s.get("enrollment_type") or None, s.get("phase") or None,
                          de.get(n, {}).get("allocation") or None, _f(s.get("number_of_arms")))
    return out
