"""Search tools over the frozen Jan 5, 2017 registry pools (DuckDB, build spec section 5).

Three pools, all built from the Jan 5, 2017 AACT snapshot only:
- similar pool: phase 2-4 interventional trials already Completed or Terminated on Jan 5, 2017,
  with the outcome as the 2017 record states it (`outcome_2017`);
- competing pool: interventional trials open to participants on Jan 5, 2017;
- cohort registry: the cohort trials' own Jan 2017 registry record (no stop reason, no outcome).

No-leak rule: nothing here reads a later snapshot. The Jan 2020 outcomes live only in the
backtest scoring and the reveal, never in these tools. Every returned column comes from an
explicit allow-list (`*_COLS` below), so a later column can't slip through by accident.
"""
from __future__ import annotations

import math
import os
import re
from pathlib import Path

POOL_FILES = {"similar_pool": "similar_pool_2017.parquet", "competing_pool": "competing_pool_2017.parquet",
              "cohort_pool": "cohort_1436_registry_2017.parquet"}
SNAPSHOT_DATE = "2017-01-05"
TOP_N = 25
COMPETING_TOP_N = 10
# Allow-lists of what the tools may return.
SIMILAR_COLS = ["nct_id", "title", "phase", "enrollment", "n_sites_2017", "lead_class", "start_date",
                "primary_completion_date", "outcome_2017", "why_stopped_2017", "conditions"]
COMPETING_COLS = ["nct_id", "title", "phase", "status_2017", "enrollment_anticipated", "n_sites_2017",
                  "lead_class", "countries"]
TRIAL_COLS = ["nct_id", "title", "phase", "status_2017", "start_date", "primary_completion_date",
              "enrollment", "enrollment_type", "n_arms", "allocation", "masking", "conditions",
              "mesh_conditions", "interventions", "keywords", "lead_class", "n_sites_2017",
              "n_countries", "countries", "minimum_age", "maximum_age", "criteria"]
# Columns that must never be returned by any tool (later-snapshot outcomes and labels).
FORBIDDEN_COLS = {"status_2020", "why_stopped", "label_poor_enrollment", "outcome_class", "split",
                  "status_2023", "last_changed_date"}
OUTCOMES = ["completed", "terminated_poor_enrollment", "terminated_other", "terminated_unknown_reason"]
PHASE_MAP = {"phase 1": ["Phase 1"], "phase 1/2": ["Phase 1/Phase 2"], "phase 2": ["Phase 2"],
             "phase 2/3": ["Phase 2/Phase 3"], "phase 3": ["Phase 3"], "phase 4": ["Phase 4"],
             "phase 2/phase 3": ["Phase 2/Phase 3"], "phase 1/phase 2": ["Phase 1/Phase 2"]}
SPONSOR_MAP = {"industry": "Industry", "nih": "NIH", "other": "Other", "academic/other": "Other",
               "academic": "Other", "cooperative group": "Other", "u.s. fed": "U.S. Fed"}
INTERVENTION_TYPES = ["Drug", "Biological", "Device", "Procedure", "Radiation", "Behavioral",
                      "Genetic", "Dietary Supplement", "Combination Product", "Diagnostic Test", "Other"]
MAX_TERMS = 8
_TERM_OK = re.compile(r"^[\w .,'/+()-]{2,60}$")


class ToolError(ValueError):
    """Bad tool arguments. The message goes back to the model so it can fix the call."""


def default_pools_dir() -> Path:
    return Path(os.environ.get("TRIAL_COPILOT_POOLS_DIR",
                               Path(__file__).resolve().parents[1] / "data" / "pools"))


def _terms(v, name: str, required: bool = False, max_n: int | None = None) -> list[str]:
    max_n = max_n or MAX_TERMS
    if v is None or v == "" or v == []:
        if required:
            raise ToolError(f"{name} is required (a list of 1-{MAX_TERMS} short terms)")
        return []
    vals = [v] if isinstance(v, str) else list(v)
    out = []
    for t in vals:
        t = str(t).strip()
        if not t:
            continue
        if not _TERM_OK.match(t):
            raise ToolError(f"{name}: term '{t[:40]}' must be 2-60 letters, digits or simple punctuation")
        out.append(t)
    if required and not out:
        raise ToolError(f"{name} is required")
    if len(out) > max_n:
        raise ToolError(f"{name}: at most {max_n} terms")
    return out


def _phases(v) -> list[str]:
    if v is None or v == "" or v == []:
        return []
    vals = [v] if isinstance(v, str) else list(v)
    out = []
    for p in vals:
        key = re.sub(r"\s+", " ", str(p).strip().lower())
        key = key.replace("phase ii/iii", "phase 2/3").replace("phase iii", "phase 3") \
                 .replace("phase ii", "phase 2").replace("phase iv", "phase 4")
        if key in PHASE_MAP:
            out += PHASE_MAP[key]
        else:
            raise ToolError(f"phase '{p}' not recognised; use e.g. 'Phase 2', 'Phase 2/3', 'Phase 3'")
    return sorted(set(out))


def _like_any(cols: list[str], terms: list[str], params: list) -> str:
    """Any term in any column, matched case-blind at the start of a word, so "SCLC" does not
    match "NSCLC" and "small cell" does not match "non-small cell", while "Alzheimer" still
    matches "Alzheimer's"."""
    parts = []
    for t in terms:
        pat = r"(^|[^a-z0-9-])" + re.escape(t.lower())
        for c in cols:
            parts.append(f"regexp_matches(lower(coalesce({c},'')), ?)")
            params.append(pat)
    return "(" + " OR ".join(parts) + ")"


def _year(v):
    try:
        return int(str(v)[:4])
    except (TypeError, ValueError):
        return None


class RegistryTools:
    """The three search tools. One instance per audit (it remembers each search's full result
    set, so later steps and the citation check can refer to it by id)."""

    def __init__(self, pools_dir: str | Path | None = None, exclude_nct: str | None = None,
                 target_enrollment: int | None = None):
        import duckdb
        self.dir = Path(pools_dir) if pools_dir else default_pools_dir()
        missing = [f for f in POOL_FILES.values() if not (self.dir / f).exists()]
        if missing:
            raise FileNotFoundError(f"pool files missing in {self.dir}: {missing}")
        self.con = duckdb.connect()
        for name, f in POOL_FILES.items():
            path = str(self.dir / f).replace("'", "''")
            self.con.execute(f"CREATE TABLE {name} AS SELECT * FROM read_parquet('{path}')")
        self.exclude = exclude_nct
        self.target = target_enrollment if target_enrollment and target_enrollment > 0 else None
        self.results: dict[str, dict] = {}
        self._n = {"S": 0, "C": 0, "T": 0}

    # ------------------------------------------------------------------ helpers
    def _id(self, prefix: str) -> str:
        self._n[prefix] += 1
        return f"{prefix}{self._n[prefix]}"

    def pool_totals(self) -> dict:
        n, k = self.con.execute("SELECT count(*), sum(CASE WHEN outcome_2017='terminated_poor_enrollment' "
                                "THEN 1 ELSE 0 END) FROM similar_pool").fetchone()
        return {"n": int(n), "events": int(k or 0)}

    # -------------------------------------------------------------------- tools
    def search_comparable_trials(self, condition_terms, phase=None, biomarker_terms=None,
                                 intervention_terms=None, intervention_type=None, sponsor_class=None,
                                 enrollment_range=None, start_year_range=None, **_ignored) -> dict:
        cond = _terms(condition_terms, "condition_terms", required=True)
        bio = _terms(biomarker_terms, "biomarker_terms")
        itv = _terms(intervention_terms, "intervention_terms")
        phases = _phases(phase)
        params: list = []
        where = [_like_any(["conditions", "mesh_conditions", "keywords", "title"], cond, params)]
        for t in bio:  # every biomarker term must appear somewhere
            where.append(_like_any(["title", "keywords", "conditions", "criteria"], [t], params))
        if itv:
            where.append(_like_any(["interventions", "mesh_interventions", "title"], itv, params))
        if phases:
            where.append("phase IN (" + ",".join("?" * len(phases)) + ")")
            params += phases
        if intervention_type:
            it = str(intervention_type).strip()
            match = [x for x in INTERVENTION_TYPES if x.lower() == it.lower()]
            if not match:
                raise ToolError(f"intervention_type must be one of {INTERVENTION_TYPES}")
            where.append("coalesce(interventions,'') ILIKE ?")
            params.append(f"%{match[0]}:%")
        if sponsor_class:
            sc = SPONSOR_MAP.get(str(sponsor_class).strip().lower())
            if not sc:
                raise ToolError("sponsor_class must be Industry, NIH, Other or U.S. Fed")
            where.append("lead_class = ?")
            params.append(sc)
        if enrollment_range:
            lo, hi = self._range(enrollment_range, "enrollment_range")
            where.append("enrollment BETWEEN ? AND ?")
            params += [lo, hi]
        if start_year_range:
            lo, hi = self._range(start_year_range, "start_year_range")
            where.append("year(start_date) BETWEEN ? AND ?")
            params += [lo, hi]
        if self.exclude:
            where.append("nct_id <> ?")
            params.append(self.exclude)
        w = " AND ".join(where)
        rows = self.con.execute(
            f"SELECT {', '.join(SIMILAR_COLS)} FROM similar_pool WHERE {w}", params).fetchall()
        recs = [dict(zip(SIMILAR_COLS, r)) for r in rows]
        counts = {o: 0 for o in OUTCOMES}
        for r in recs:
            counts[r["outcome_2017"]] = counts.get(r["outcome_2017"], 0) + 1
        recs.sort(key=self._order)
        rid = self._id("S")
        args = {"condition_terms": cond, "phase": phases, "biomarker_terms": bio,
                "intervention_terms": itv, "intervention_type": intervention_type,
                "sponsor_class": sponsor_class, "enrollment_range": enrollment_range,
                "start_year_range": start_year_range}
        self.results[rid] = {"tool": "search_comparable_trials", "args": args,
                             "nct_ids": [r["nct_id"] for r in recs], "outcome_counts": counts,
                             "rows": recs}
        return {"result_id": rid, "n_matched": len(recs),
                "outcome_counts_2017": counts,
                "poor_enrollment_share": (round(counts["terminated_poor_enrollment"] / len(recs), 3)
                                          if recs else None),
                f"top_{TOP_N}": [self._short(r) for r in recs[:TOP_N]]}

    def count_competing_trials(self, condition_terms, phase=None, countries=None, **_ignored) -> dict:
        cond = _terms(condition_terms, "condition_terms", required=True)
        ctry = _terms(countries, "countries", max_n=25)  # multinational trials list many
        phases = _phases(phase)
        params: list = []
        where = [_like_any(["conditions", "mesh_conditions", "keywords", "title"], cond, params)]
        if phases:
            where.append("phase IN (" + ",".join("?" * len(phases)) + ")")
            params += phases
        if ctry:
            where.append(_like_any(["countries"], ctry, params))
        if self.exclude:
            where.append("nct_id <> ?")
            params.append(self.exclude)
        rows = self.con.execute(
            f"SELECT {', '.join(COMPETING_COLS)} FROM competing_pool WHERE {' AND '.join(where)} "
            "ORDER BY n_sites_2017 DESC NULLS LAST, nct_id", params).fetchall()
        recs = [dict(zip(COMPETING_COLS, r)) for r in rows]
        rid = self._id("C")
        by_phase: dict[str, int] = {}
        for r in recs:
            by_phase[r["phase"] or "N/A"] = by_phase.get(r["phase"] or "N/A", 0) + 1
        self.results[rid] = {"tool": "count_competing_trials",
                             "args": {"condition_terms": cond, "phase": phases, "countries": ctry},
                             "nct_ids": [r["nct_id"] for r in recs], "rows": recs}
        return {"result_id": rid, "snapshot_date": SNAPSHOT_DATE, "n_recruiting": len(recs),
                "total_sites": int(sum(r["n_sites_2017"] or 0 for r in recs)),
                "by_phase": by_phase,
                f"top_{COMPETING_TOP_N}_by_sites": [
                    {"nct_id": r["nct_id"], "title": (r["title"] or "")[:90], "phase": r["phase"],
                     "sites": r["n_sites_2017"], "sponsor": r["lead_class"]}
                    for r in recs[:COMPETING_TOP_N]]}

    def get_trial(self, nct_id, **_ignored) -> dict:
        nid = str(nct_id or "").strip().upper()
        if not re.fullmatch(r"NCT\d{8}", nid):
            raise ToolError("nct_id must look like NCT01234567")
        if self.exclude and nid == self.exclude:
            raise ToolError("that is the trial being audited; its own record is not a comparable")
        rid = self._id("T")
        for pool, extra in (("similar_pool", ["outcome_2017", "why_stopped_2017"]), ("competing_pool", []),
                            ("cohort_pool", [])):
            cols = [c for c in self._columns(pool) if c in TRIAL_COLS or c in extra]
            row = self.con.execute(f"SELECT {', '.join(cols)} FROM {pool} WHERE nct_id = ?", [nid]).fetchone()
            if row:
                rec = dict(zip(cols, row))
                for k in ("start_date", "primary_completion_date"):
                    if rec.get(k) is not None:
                        rec[k] = str(rec[k])[:10]
                if rec.get("criteria"):
                    rec["criteria"] = re.sub(r"\s+", " ", rec["criteria"])[:1500]
                rec["pool"] = pool
                self.results[rid] = {"tool": "get_trial", "args": {"nct_id": nid}, "nct_ids": [nid]}
                return {"result_id": rid, "record_as_of": SNAPSHOT_DATE, **rec}
        self.results[rid] = {"tool": "get_trial", "args": {"nct_id": nid}, "nct_ids": []}
        return {"result_id": rid, "found": False, "nct_id": nid}

    def registry_2017(self, nct_id: str) -> dict | None:
        """The audited trial's own Jan 2017 registry record (for the site/month fallbacks).
        Code-side only: never sent to the model as a tool result."""
        cols = [c for c in self._columns("cohort_pool") if c in TRIAL_COLS and c != "criteria"]
        for pool in ("cohort_pool", "competing_pool"):
            pc = [c for c in cols if c in self._columns(pool)]
            row = self.con.execute(f"SELECT {', '.join(pc)} FROM {pool} WHERE nct_id = ?",
                                   [str(nct_id).upper()]).fetchone()
            if row:
                return dict(zip(pc, row))
        return None

    # ------------------------------------------------------------------ helpers
    def _columns(self, pool: str) -> list[str]:
        cols = [r[0] for r in self.con.execute(f"DESCRIBE {pool}").fetchall()]
        return [c for c in cols if c not in FORBIDDEN_COLS]

    @staticmethod
    def _range(v, name):
        try:
            lo, hi = (int(float(v[0])), int(float(v[1])))
        except (TypeError, ValueError, IndexError, KeyError):
            raise ToolError(f"{name} must be [min, max]") from None
        if lo > hi:
            lo, hi = hi, lo
        return lo, hi

    def _order(self, r):
        """Closest planned size first (when known), then most recent start, then NCT id."""
        size = 9.0
        if self.target and r["enrollment"]:
            size = abs(math.log(max(r["enrollment"], 1) / self.target))
        y = _year(r["start_date"]) or 0
        return (round(size, 2), -y, r["nct_id"])

    @staticmethod
    def _short(r):
        return {"nct_id": r["nct_id"], "title": (r["title"] or "")[:90], "phase": r["phase"],
                "enrollment": r["enrollment"], "sites": r["n_sites_2017"], "sponsor": r["lead_class"],
                "start_year": _year(r["start_date"]), "outcome_2017": r["outcome_2017"],
                "stop_reason_2017": (r["why_stopped_2017"] or "")[:80] or None}

    def call(self, name: str, args: dict) -> dict:
        fn = {"search_comparable_trials": self.search_comparable_trials,
              "count_competing_trials": self.count_competing_trials,
              "get_trial": self.get_trial}.get(name)
        if fn is None:
            raise ToolError(f"unknown tool '{name}'")
        if not isinstance(args, dict):
            raise ToolError("arguments must be a JSON object")
        return fn(**{k: v for k, v in args.items() if k != "reason"})


TOOL_SPECS = [
    {"type": "function", "function": {
        "name": "search_comparable_trials",
        "description": ("Search phase 2-4 interventional trials whose outcome was known on Jan 5, 2017 "
                        "(completed or terminated, outcome as the 2017 registry record states it). "
                        "Returns the match count, outcome counts and the 25 trials closest in planned size. "
                        "condition_terms are OR-ed; biomarker_terms are AND-ed; intervention_terms are OR-ed."),
        "parameters": {"type": "object", "properties": {
            "reason": {"type": "string", "description": "One line: why this search, and why widen or narrow"},
            "condition_terms": {"type": "array", "items": {"type": "string"},
                                "description": "Disease terms matched in conditions, MeSH terms, keywords and title"},
            "phase": {"type": "array", "items": {"type": "string"}, "description": "e.g. ['Phase 2','Phase 3']"},
            "biomarker_terms": {"type": "array", "items": {"type": "string"}},
            "intervention_terms": {"type": "array", "items": {"type": "string"},
                                   "description": "Drug names or classes matched in interventions"},
            "intervention_type": {"type": "string", "enum": INTERVENTION_TYPES},
            "sponsor_class": {"type": "string", "enum": ["Industry", "NIH", "Other", "U.S. Fed"]},
            "enrollment_range": {"type": "array", "items": {"type": "integer"}, "description": "[min, max]"},
            "start_year_range": {"type": "array", "items": {"type": "integer"}, "description": "[from, to]"}},
            "required": ["reason", "condition_terms"]}}},
    {"type": "function", "function": {
        "name": "count_competing_trials",
        "description": ("Count interventional trials open to participants on Jan 5, 2017 for a condition "
                        "(any phase unless given), optionally in given countries. Returns the count, "
                        "their total sites, a phase breakdown and the 10 largest by sites."),
        "parameters": {"type": "object", "properties": {
            "reason": {"type": "string"},
            "condition_terms": {"type": "array", "items": {"type": "string"}},
            "phase": {"type": "array", "items": {"type": "string"}},
            "countries": {"type": "array", "items": {"type": "string"}}},
            "required": ["reason", "condition_terms"]}}},
    {"type": "function", "function": {
        "name": "get_trial",
        "description": "One trial's registry record as of Jan 5, 2017 (including the eligibility text, cut to 1,500 characters).",
        "parameters": {"type": "object", "properties": {
            "reason": {"type": "string"}, "nct_id": {"type": "string"}},
            "required": ["reason", "nct_id"]}}},
]
