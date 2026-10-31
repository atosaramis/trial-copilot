"""Compare facts extracted from a protocol with the trial's Jan 2017 registry record.

Deterministic: no model calls. Each mismatch carries a severity and, where the protocol text is
available, the page and a short quote that states the protocol value. Known traps are flagged:

- ranges ("20-25 sites"): if any value in the range agrees with the registry, it is not a mismatch;
- statistical planning assumptions ("we assume 40 enrolling sites") read as a site plan;
- 1-2 site placeholder registry entries against a large protocol plan;
- the registry's number also appearing in the protocol (for example evaluable vs enrolled);
- a card value we cannot find anywhere in the protocol text.

A mismatch is a disagreement between two documents. It says nothing about which one is right.

Rule versions (pass `rules=` to `find_mismatches`; old results stay reproducible):

- "v2" (2026-10-27, first scan): the rules above.
- "v3" (default): adds the patterns the investigation agent found among its extraction-error
  verdicts on 100 tuning trials:
  * bounds: "a minimum of three centres" or "20 sites or more" is a minimum, so a registry value
    that meets it is cleared; "up to 5 centers" is a maximum, flagged `upper_bound` (a doubtful
    comparison, not cleared: "up to 65 sites" against 9 registered is often a lagging registry);
  * enrollment funnels: each count gets a role from the nearest keyword (screened, enrolled,
    randomized, completed/evaluable, stage). When the card took a completed/evaluable count and the
    registry equals the protocol's enrolled/consented count, the card read the wrong number and the
    mismatch is cleared (`count_definition`). Any other match of the registry number to a funnel
    count is flagged `count_definition` (doubtful, low), so a later registry correction still shows;
  * multi-part designs (crossover sequences, Part 2 / Step 2, extensions, run-ins, observational
    groups, several sub-studies): arm counts are flagged `multi_part_design`, a doubtful reading;
  * combined phases: when the card has one phase but the protocol states a combined phase covering
    both ("Phase III/IV" vs a Phase 4 registry), the mismatch is low and quotes the combined phase;
  * randomization quotes about a previous study are skipped (`other_study` if nothing else);
  * site counts given as networks "and their satellites" are flagged `satellite_sites`;
  * labelled fields "Enrollment: 60" and "Sites 20 or more" are found;
  * a card with `planned_enrollment_values` (the protocol states different planned totals, set by
    app/design_checks.py) gives one low `protocol_inconsistent` enrollment row listing every value.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

FIELDS = ("sites", "countries", "enrollment", "phase", "randomized", "arms")
SEVERITIES = ("high", "medium", "low")

# Traps that make a mismatch doubtful on our side (the reading, not the registry).
READING_TRAPS = {"range", "planning_assumption", "quote_not_found", "registry_value_in_protocol",
                 "evaluable_count",
                 # v3 only
                 "multi_part_design", "other_study", "satellite_sites", "upper_bound", "count_definition",
                 # the protocol contradicts itself: not our misreading, but no single value to compare
                 "protocol_inconsistent"}
RULES = ("v2", "v3")
DEFAULT_RULES = "v3"

_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen twenty".split())}
_WORDS.update({"thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
               "ninety": 90, "hundred": 100})
_NUM = r"(\d{1,3}(?:,\d{3})+|\d{1,5}|" + "|".join(sorted(_WORDS, key=len, reverse=True)) + r")"
_RANGE = _NUM + r"(?:\s*(?:-|–|—|to)\s*" + _NUM + r")?"
_FILLER = r"(?:\s+(?!(?:and|or|of|in|per|with|from)\b)[A-Za-z][A-Za-z.\-/]*){0,3}?"
_SITE_NOUN = r"(?:sites?|centers?|centres?|institutions?|hospitals?|clinics|investigators)\b"
_PERSON_NOUN = (r"(?:patients?|subjects?|participants?|individuals?|women|men|children|adults?|"
                r"volunteers?|infants?|persons?|people|veterans?|smokers?|survivors?|mothers?|caregivers?|"
                r"students?|families|couples|pairs|dyads|eyes|neonates?|newborns?|girls|boys|adolescents?|cases)\b")
_ABOUT = r"(?:(?:approximately|approx\.|about|up to|a total of|total of|maximum|max\.?)\s*)?"
_PRANGE = r"\(?" + _RANGE + r"\)?"
SITE_RX = (re.compile(r"\b" + _PRANGE + _FILLER + r"\s+" + _SITE_NOUN, re.I),
           re.compile(r"\bnumber of (?:[a-z]+ )?(?:sites|centers|centres|institutions)(?: planned)?\s*[:=]?\s*"
                      + _ABOUT + _RANGE, re.I))
COUNTRY_RX = (re.compile(r"\b" + _PRANGE + _FILLER + r"\s+countr(?:y|ies)\b", re.I),
              re.compile(r"\bnumber of countries\s*[:=]?\s*" + _ABOUT + _RANGE, re.I))
PERSON_RX = (re.compile(r"\b" + _PRANGE + _FILLER + r"\s+" + _PERSON_NOUN, re.I),
             re.compile(r"(?:\bn\s*=\s*|\bsample size (?:of|is|will be)\s*" + _ABOUT + r"|\btotal (?:sample(?: size)?|n)\s*"
                        r"(?:of|=|:)?\s*|\bnumber of (?:patients|subjects|participants)(?: planned| to be (?:enrolled|randomi[sz]ed))?"
                        r"\s*[:=]?\s*" + _ABOUT + r")" + _RANGE, re.I))
ARMS_RX = re.compile(r"\b" + _NUM + r"(?:\s+[A-Za-z\-]+){0,2}?\s+(?:arms?|groups?|cohorts?)\b", re.I)
PHASE_RX = re.compile(r"\bphase\s*(?:I{1,3}V?|IV|[1-4])(?:\s*[/ab]\s*(?:I{1,3}|[1-4]))?\b", re.I)
RANDOM_RX = re.compile(r"\b(?:non-?\s?randomi[sz]ed|randomi[sz]ed|single[- ]arm|open[- ]label,? single)\b", re.I)

# ---- v3 additions (v2 never uses these) ----
SITE_RX_V3 = SITE_RX + (re.compile(r"\b(?:sites|centers|centres|study centers)\s*[:=]?\s*" + _ABOUT + _NUM
                                   + r"(?=\s*(?:or more|or greater|\+|\(|$|[.;,]))", re.I),)
PERSON_RX_V3 = PERSON_RX + (re.compile(r"\b(?:enrollment|enrolment|planned enrollment|target enrollment)\s*[:=]\s*"
                                       + _ABOUT + _RANGE, re.I),)
PHASE_RX_V3 = re.compile(r"\bphase\s*(?:IV|I{1,3}|[1-4])(?:\s*[/ab\-]\s*(?:IV|I{1,3}|[1-4]))?(?![A-Za-z])", re.I)
UPPER_RX = re.compile(r"(?:up to|a maximum of|maximum of|maximum|max\.?|no more than|not more than|not to exceed|"
                      r"not exceed(?:ing)?|at most)\s*$", re.I)
LOWER_RX = re.compile(r"(?:at least|a minimum of|minimum of|minimum|no fewer than|no less than|more than|over)\s*$", re.I)
LOWER_POST_RX = re.compile(r"^\s*(?:\w+\s+){0,3}?(?:or more|or greater|or above)\b|^\s*\+", re.I)
FUNNEL_RX = re.compile(r"screen|enrol|consent|randomi[sz]|complet|evaluable|analy[sz]|recruit|accru|pilot|stage|"
                       r"per[- ]protocol|drop[- ]?out|withdraw|target|sample size|dyads?|pairs?|mothers?|infants?", re.I)
MULTIPART_RX = re.compile(r"cross-?over|treatment sequences?|sequence groups?|counterbalanc|treatment periods?|"
                          r"intervention periods?|\bpart (?:2|ii|b)\b|\bstep (?:2|ii)\b|\bstage (?:2|ii)\b|"
                          r"extension (?:phase|period|study|group|cohort|arm)|open[- ]label (?:extension|lead[- ]in|period|run[- ]in)|"
                          r"run[- ]in (?:period|phase)|observational (?:group|cohort|arm)|\bcohort (?:2|b)\b|"
                          r"sub-?stud(?:y|ies)|(?:two|three|four|2|3|4) (?:separate )?studies|randomi[sz]ed withdrawal", re.I)
PRIOR_RX = re.compile(r"\b(?:were|was|had been) (?:\w+ )?randomi[sz]ed|\(\d{1,3}(?:[,\u2013-]\s?\d{1,3})*\)|\[\d{1,3}\]|"
                      r"of the [A-Z][A-Z0-9]*-[A-Z0-9-]+ (?:study|trial)|\b(?:19|20)\d\d\s?;\s?\d|\bet al\b|previous(?:ly)?|prior (?:study|trial|studies|trials)|earlier (?:study|trial)|parent (?:study|trial)|"
                      r"original (?:study|trial)|feeder|et al|published|lead[- ]in study|in (?:the|a) (?:phase \w+ )?"
                      r"(?:study|trial) [A-Z]{2,}[-\d]", re.I)
ROLE_RX = re.compile(r"(?P<screened>screen(?!\s*fail))|(?P<enrolled>enrol|consent|recruit|accru|total sample|sample size)|"
                     r"(?P<randomized>randomi[sz])|(?P<completed>complet|evaluable|analy[sz]able|per[- ]protocol)|"
                     r"(?P<stage>pilot|stage|phase [12i]|part [12ab])", re.I)
SATELLITE_RX = re.compile(r"satellite|affiliat|sub-?sites?|associated (?:sites|centers|centres)|network", re.I)

ASSUMPTION_RX = re.compile(r"assum|accrual rate|per (?:site|center|centre) per month|projected accrual|"
                           r"expected to accrue|power calculation|sample size calculation|simulat", re.I)
EVALUABLE_RX = re.compile(r"evaluable|completers?|complete the study|per[- ]protocol|analy[sz]able", re.I)


@dataclass(frozen=True)
class Evidence:
    page: int | None          # 1-based page in the protocol PDF
    quote: str | None         # short quote around the number, whitespace collapsed
    kind: str                 # stated | range | planning_assumption | not_found | no_text
    low: float | None = None
    high: float | None = None


@dataclass(frozen=True)
class Mismatch:
    nct_id: str
    field: str
    protocol_value: object
    registry_value: object
    severity: str             # high | medium | low
    direction: str            # protocol_higher | protocol_lower | differs
    traps: tuple[str, ...] = ()
    evidence: Evidence = Evidence(None, None, "no_text")
    note: str = ""

    @property
    def doubtful_reading(self) -> bool:
        return bool(READING_TRAPS & set(self.traps))


@dataclass
class FinderResult:
    nct_id: str
    mismatches: list[Mismatch] = field(default_factory=list)
    cleared: list[Mismatch] = field(default_factory=list)   # looked like a mismatch, a trap explains it
    compared: list[str] = field(default_factory=list)       # fields where both sides had a value


# ---------- small helpers ----------

def _num(v) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _tok(s: str | None) -> float | None:
    if s is None:
        return None
    s = s.lower().replace(",", "")
    return float(_WORDS[s]) if s in _WORDS else float(s)


def _clip(text: str, a: int, b: int, pad: int = 90) -> str:
    lo, hi = max(0, a - pad), min(len(text), b + pad)
    return ("…" if lo else "") + text[lo:hi].strip() + ("…" if hi < len(text) else "")


def load_pages(path: str | Path) -> list[str]:
    """Protocol text with one form feed per page (pdftotext output), whitespace collapsed per page."""
    raw = Path(path).read_text(errors="replace")
    pages = [re.sub(r"\s+", " ", p) for p in raw.split("\f")]
    return pages if has_text_layer(pages) else []


def has_text_layer(pages: list[str], min_chars_per_page: int = 200, max_short_word_share: float = 0.33) -> bool:
    """False for scans (almost no text) and for garbled text layers where words are split into
    fragments ("A dv isort odis cusss"). Their quotes have to come from the page images instead."""
    if not pages or sum(len(p) for p in pages) / len(pages) < min_chars_per_page:
        return False
    words = re.findall(r"[A-Za-z]+", " ".join(pages))
    return sum(len(w) <= 2 for w in words) / max(1, len(words)) <= max_short_word_share


def normalize_phase(p) -> frozenset[str] | None:
    if not isinstance(p, str) or not p.strip():
        return None
    s = p.lower().replace("phase", " ").replace("early", " 0 ")
    if s.strip() in ("n/a", "na", "not applicable", "none"):
        return frozenset({"na"})
    roman = {"iv": "4", "iii": "3", "ii": "2", "i": "1"}
    parts = re.findall(r"(?<![a-z])(iv|iii|ii|i|[0-4])(?![c-z])", s)
    out = frozenset(roman.get(x, x) for x in parts)
    return out or None


def card_randomized(allocation) -> bool | None:
    a = str(allocation or "").lower().strip()
    if not a:
        return None
    if "non" in a or "single" in a or a in ("n/a", "na", "none"):
        return False
    return "random" in a


def registry_randomized(allocation) -> bool | None:
    if not isinstance(allocation, str) or not allocation.strip():
        return None
    return allocation.strip().lower() == "randomized"


# ---------- finding the protocol statement ----------

@dataclass(frozen=True)
class _Hit:
    page: int
    low: float
    high: float
    quote: str
    assumption: bool
    evaluable: bool
    bound: str | None = None    # v3: "max" (up to N) or "min" (at least N)
    context: str = ""           # v3: about 120 characters either side
    role: str | None = None     # v3: screened | enrolled | randomized | completed | stage (nearest keyword)


def _role(t: str, a: int, b: int) -> str | None:
    """Funnel role of the number at t[a:b]: the closest keyword within 50 chars before or 40 after."""
    best = None
    for off, seg in ((max(0, a - 50), t[max(0, a - 50): a]), (b, t[b: b + 40])):
        for m in ROLE_RX.finditer(seg):
            d = (a - (off + m.end())) if off < a else (off + m.start() - b)
            if best is None or d < best[0]:
                best = (d, m.lastgroup)
    return best[1] if best else None


def _hits(pages: list[str], rxs) -> list[_Hit]:
    out = []
    rxs = rxs if isinstance(rxs, (tuple, list)) else (rxs,)
    for i, t in enumerate(pages, start=1):
        for m in (m for rx in rxs for m in rx.finditer(t)):
            try:
                a = _tok(m.group(1))
                b = _tok(m.group(2)) if m.lastindex and m.lastindex >= 2 and m.group(2) else a
            except (ValueError, IndexError):
                continue
            if a is None or b is None:
                continue
            lo, hi = min(a, b), max(a, b)
            ctx = t[max(0, m.start() - 220): m.end() + 220]
            pre = t[max(0, m.start() - 60): m.end()]
            before = t[max(0, m.start() - 30): m.start()] + t[m.start(): m.start(1)]
            end = m.end(2) if m.lastindex and m.lastindex >= 2 and m.group(2) else m.end(1)
            bound = ("max" if UPPER_RX.search(before) else
                     "min" if LOWER_RX.search(before) or LOWER_POST_RX.search(t[end: end + 40]) else None)
            out.append(_Hit(i, lo, hi, _clip(t, m.start(), m.end()), bool(ASSUMPTION_RX.search(ctx)),
                            bool(EVALUABLE_RX.search(pre)), bound if lo == hi else None,
                            t[max(0, m.start() - 120): m.end() + 120], _role(t, m.start(1), end)))
    return out


def locate(pages: list[str] | None, rx: re.Pattern, value: float, rules: str = "v2") -> tuple[Evidence, list[_Hit]]:
    """Best protocol statement for `value`: an exact stated number beats a range end, which beats
    a planning assumption (v3: a stated bound beats a bare number). Returns the evidence and every
    hit (for the other-number checks)."""
    if not pages:
        return Evidence(None, None, "no_text"), []
    hits = _hits(pages, rx)
    match = [h for h in hits if value in (h.low, h.high)]
    if not match:
        return Evidence(None, None, "not_found"), hits
    if rules == "v2":
        match.sort(key=lambda h: (h.assumption, h.low != h.high, h.page))
    else:
        match.sort(key=lambda h: (h.assumption, h.bound is None, h.low != h.high, h.page))
    h = match[0]
    kind = "planning_assumption" if h.assumption else ("range" if h.low != h.high else "stated")
    if rules != "v2" and h.bound and not h.assumption:
        kind = "upper_bound" if h.bound == "max" else "lower_bound"
    return Evidence(h.page, h.quote, kind, h.low, h.high), hits


# ---------- the comparison ----------

def _ratio(p: float, r: float) -> float:
    lo, hi = min(p, r), max(p, r)
    return math.inf if lo <= 0 else hi / lo


def _dir(p: float, r: float) -> str:
    return "protocol_higher" if p > r else "protocol_lower"


def site_tolerance(r: float) -> float:
    return max(2.0, 0.20 * r)


def enrollment_tolerance(r: float) -> float:
    return 0.10 * r


def _numeric(nct, fld, p, r, tol, rx, pages, sev_fn, res: FinderResult, placeholder=False, rules="v2"):
    res.compared.append(fld)
    if abs(p - r) <= tol(r):
        return
    ev, hits = locate(pages, rx, p, rules)
    traps = []
    if rules != "v2":
        clear = None
        p_roles = {h.role for h in hits if p in (h.low, h.high) and not h.assumption}
        r_roles = {h.role for h in hits if h.low == h.high and abs(h.low - r) <= tol(r) and not h.assumption} - {None}
        if ev.kind == "lower_bound" and r >= p - tol(r):
            clear = ("lower_bound", "the protocol gives a minimum and the registry value meets it")
        elif fld == "enrollment" and "completed" in p_roles and "enrolled" in r_roles and p < r:
            clear = ("count_definition", "the card took the protocol's completed/evaluable count; the registry "
                                         "matches the protocol's enrolled count")
        if clear:
            res.cleared.append(Mismatch(nct, fld, p, r, "low", _dir(p, r), (clear[0],), ev, clear[1]))
            return
        if ev.kind in ("upper_bound", "lower_bound"):
            traps.append(ev.kind)
        if fld == "enrollment" and r_roles:
            traps.append("count_definition")
        if fld == "arms" and pages and any(MULTIPART_RX.search(t) for t in pages):
            traps.append("multi_part_design")
        if fld == "sites" and r > p and ev.quote and SATELLITE_RX.search(ev.quote):
            traps.append("satellite_sites")
    if ev.kind == "not_found" and fld != "arms":   # arm counts are rarely written as a number
        traps.append("quote_not_found")
    if ev.kind == "range":
        traps.append("range")
        if any(abs(x - r) <= tol(r) for x in (ev.low, ev.high)) or ev.low <= r <= ev.high:
            res.cleared.append(Mismatch(nct, fld, p, r, "low", _dir(p, r), ("range",), ev,
                                        "the protocol gives a range that includes the registry value"))
            return
    if ev.kind == "planning_assumption":
        traps.append("planning_assumption")
    if fld == "enrollment" and any(h.evaluable and (h.low == p or h.high == p) for h in hits):
        traps.append("evaluable_count")
    if fld in ("sites", "enrollment") and any(h.low == h.high == r and not h.assumption for h in hits):
        traps.append("registry_value_in_protocol")
    if placeholder and r <= 2 and p >= 10:
        traps.append("registry_placeholder")
    sev = sev_fn(p, r)
    if set(traps) & {"planning_assumption", "registry_placeholder", "multi_part_design", "count_definition"}:
        sev = "low"
    elif set(traps) & READING_TRAPS and sev == "high":
        sev = "medium"
    res.mismatches.append(Mismatch(nct, fld, p, r, sev, _dir(p, r), tuple(traps), ev))


def _sev_sites(p, r):
    return "high" if _ratio(p, r) >= 2 else "medium"


def _sev_enrollment(p, r):
    q = _ratio(p, r)
    return "high" if q >= 2 else "medium" if q >= 1.5 else "low"


def _sev_countries(p, r):
    return "medium" if abs(p - r) > 2 or _ratio(p, r) >= 2 else "low"


def _sev_arms(p, r):
    return "medium" if abs(p - r) >= 2 else "low"


def _first(pages, rx) -> Evidence:
    if not pages:
        return Evidence(None, None, "no_text")
    for i, t in enumerate(pages, start=1):
        m = rx.search(t)
        if m:
            return Evidence(i, _clip(t, m.start(), m.end()), "stated")
    return Evidence(None, None, "not_found")


# "presented in a randomized order", "randomized sequence of stimuli": procedure order, not allocation.
CITE_RX = re.compile(r"\b(?:19|20)\d\d\s?;\s?\d|\bet al\b")  # 3+ on a page: a reference list
ORDER_RX = re.compile(r"^\s*(?:order|sequence)\b", re.I)


def _first_random(pages) -> tuple[Evidence, tuple[str, ...]]:
    """v3: the first randomization statement that is not about a previous study."""
    if not pages:
        return Evidence(None, None, "no_text"), ("quote_not_found",)
    prior = None
    for i, t in enumerate(pages, start=1):
        refs = len(CITE_RX.findall(t)) >= 3
        for m in RANDOM_RX.finditer(t):
            if ORDER_RX.match(t[m.end(): m.end() + 12]):
                continue
            if refs or PRIOR_RX.search(t[max(0, m.start() - 150): m.end() + 80]):
                prior = prior or Evidence(i, _clip(t, m.start(), m.end()), "stated")
                continue
            return Evidence(i, _clip(t, m.start(), m.end()), "stated"), ()
    return (prior, ("other_study",)) if prior else (Evidence(None, None, "not_found"), ("quote_not_found",))


def _inconsistent_enrollment(nct, vals: list[float], r: float, pages, res: FinderResult) -> None:
    """v3: the protocol itself states different planned totals. Reported as one low, doubtful
    enrollment row quoting the first total; the registry is compared with every stated value."""
    res.compared.append("enrollment")
    ev, _ = locate(pages, PERSON_RX_V3, vals[0], "v3")
    shown = " / ".join(f"{v:g}" for v in vals)
    match = [v for v in vals if abs(v - r) <= enrollment_tolerance(r)]
    note = (f"the protocol states different planned totals ({shown}); "
            + (f"the registry matches {match[0]:g}" if match else "the registry matches none of them"))
    res.mismatches.append(Mismatch(nct, "enrollment", shown, r, "low", "differs", ("protocol_inconsistent",), ev, note))


def find_mismatches(nct_id: str, card: dict, registry: dict, pages: list[str] | None = None,
                    rules: str = DEFAULT_RULES) -> FinderResult:
    """`card`: extracted protocol facts (card_schema keys). `registry`: the Jan 2017 record with keys
    phase, allocation, n_arms, enrollment, n_sites_2017, n_countries. `pages`: protocol text per page.
    `rules`: "v2" or "v3" (see the module docstring)."""
    if rules not in RULES:
        raise ValueError(f"unknown rules {rules!r}")
    v3 = rules != "v2"
    res = FinderResult(nct_id)
    p, r = _num(card.get("planned_sites")), _num(registry.get("n_sites_2017"))
    if p and r:
        _numeric(nct_id, "sites", p, r, site_tolerance, SITE_RX_V3 if v3 else SITE_RX, pages, _sev_sites, res,
                 placeholder=True, rules=rules)
    p, r = _num(card.get("planned_countries")), _num(registry.get("n_countries"))
    if p and r:
        _numeric(nct_id, "countries", p, r, lambda _r: 0, COUNTRY_RX, pages, _sev_countries, res, rules=rules)
    p, r = _num(card.get("planned_enrollment")), _num(registry.get("enrollment"))
    vals = [v for v in (_num(x) for x in card.get("planned_enrollment_values") or []) if v]
    if v3 and len(vals) >= 2 and r:
        _inconsistent_enrollment(nct_id, vals, r, pages, res)
    elif p and r:
        _numeric(nct_id, "enrollment", p, r, enrollment_tolerance, PERSON_RX_V3 if v3 else PERSON_RX, pages,
                 _sev_enrollment, res, rules=rules)
    p, r = _num(card.get("n_arms")), _num(registry.get("n_arms"))
    if p and r:
        _numeric(nct_id, "arms", p, r, lambda _r: 0, ARMS_RX, pages, _sev_arms, res, rules=rules)
    a, b = normalize_phase(card.get("phase")), normalize_phase(registry.get("phase"))
    if a and b:
        res.compared.append("phase")
        combined = None
        if a != b and v3 and pages and not (a & b):
            combined = next((Evidence(i, _clip(t, m.start(), m.end()), "stated")
                             for i, t in enumerate(pages[:5], 1) for m in PHASE_RX_V3.finditer(t)
                             if (a | b) <= (normalize_phase(m.group(0)) or frozenset())), None)
        if combined:
            res.mismatches.append(Mismatch(nct_id, "phase", card.get("phase"), registry.get("phase"), "low", "differs",
                                           ("combined_phase",), combined,
                                           "overlapping phases: the protocol states a combined phase covering both"))
        elif a != b:
            sev = "low" if a & b else "high"
            res.mismatches.append(Mismatch(nct_id, "phase", card.get("phase"), registry.get("phase"), sev,
                                           "differs", (), _first(pages, PHASE_RX),
                                           "overlapping phases" if a & b else ""))
    a, b = card_randomized(card.get("allocation")), registry_randomized(registry.get("allocation"))
    if a is not None and b is not None:
        res.compared.append("randomized")
        if a != b:
            if v3:
                ev, traps = _first_random(pages)
            else:
                ev = _first(pages, RANDOM_RX)
                traps = () if ev.kind == "stated" else ("quote_not_found",)
            res.mismatches.append(Mismatch(nct_id, "randomized", card.get("allocation"), registry.get("allocation"),
                                           "high" if not (v3 and traps) else "medium", "differs", traps, ev))
    return res
