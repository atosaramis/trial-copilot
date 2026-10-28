"""Compare facts extracted from a protocol with the trial's Jan 2017 registry record.

Deterministic: no model calls. Each mismatch carries a severity and, where the protocol text is
available, the page and a short quote that states the protocol value. Known traps are flagged:

- ranges ("20-25 sites"): if any value in the range agrees with the registry, it is not a mismatch;
- statistical planning assumptions ("we assume 40 enrolling sites") read as a site plan;
- 1-2 site placeholder registry entries against a large protocol plan;
- the registry's number also appearing in the protocol (for example evaluable vs enrolled);
- a card value we cannot find anywhere in the protocol text.

A mismatch is a disagreement between two documents. It says nothing about which one is right.
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
                 "evaluable_count"}

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
            out.append(_Hit(i, lo, hi, _clip(t, m.start(), m.end()), bool(ASSUMPTION_RX.search(ctx)),
                            bool(EVALUABLE_RX.search(pre))))
    return out


def locate(pages: list[str] | None, rx: re.Pattern, value: float) -> tuple[Evidence, list[_Hit]]:
    """Best protocol statement for `value`: an exact stated number beats a range end, which beats
    a planning assumption. Returns the evidence and every hit (for the other-number checks)."""
    if not pages:
        return Evidence(None, None, "no_text"), []
    hits = _hits(pages, rx)
    match = [h for h in hits if value in (h.low, h.high)]
    if not match:
        return Evidence(None, None, "not_found"), hits
    match.sort(key=lambda h: (h.assumption, h.low != h.high, h.page))
    h = match[0]
    kind = "planning_assumption" if h.assumption else ("range" if h.low != h.high else "stated")
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


def _numeric(nct, fld, p, r, tol, rx, pages, sev_fn, res: FinderResult, placeholder=False):
    res.compared.append(fld)
    if abs(p - r) <= tol(r):
        return
    ev, hits = locate(pages, rx, p)
    traps = []
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
    if set(traps) & {"planning_assumption", "registry_placeholder"}:
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


def find_mismatches(nct_id: str, card: dict, registry: dict, pages: list[str] | None = None) -> FinderResult:
    """`card`: extracted protocol facts (card_schema keys). `registry`: the Jan 2017 record with keys
    phase, allocation, n_arms, enrollment, n_sites_2017, n_countries. `pages`: protocol text per page."""
    res = FinderResult(nct_id)
    p, r = _num(card.get("planned_sites")), _num(registry.get("n_sites_2017"))
    if p and r:
        _numeric(nct_id, "sites", p, r, site_tolerance, SITE_RX, pages, _sev_sites, res, placeholder=True)
    p, r = _num(card.get("planned_countries")), _num(registry.get("n_countries"))
    if p and r:
        _numeric(nct_id, "countries", p, r, lambda _r: 0, COUNTRY_RX, pages, _sev_countries, res)
    p, r = _num(card.get("planned_enrollment")), _num(registry.get("enrollment"))
    if p and r:
        _numeric(nct_id, "enrollment", p, r, enrollment_tolerance, PERSON_RX, pages, _sev_enrollment, res)
    p, r = _num(card.get("n_arms")), _num(registry.get("n_arms"))
    if p and r:
        _numeric(nct_id, "arms", p, r, lambda _r: 0, ARMS_RX, pages, _sev_arms, res)
    a, b = normalize_phase(card.get("phase")), normalize_phase(registry.get("phase"))
    if a and b:
        res.compared.append("phase")
        if a != b:
            sev = "low" if a & b else "high"
            res.mismatches.append(Mismatch(nct_id, "phase", card.get("phase"), registry.get("phase"), sev,
                                           "differs", (), _first(pages, PHASE_RX),
                                           "overlapping phases" if a & b else ""))
    a, b = card_randomized(card.get("allocation")), registry_randomized(registry.get("allocation"))
    if a is not None and b is not None:
        res.compared.append("randomized")
        if a != b:
            ev = _first(pages, RANDOM_RX)
            res.mismatches.append(Mismatch(nct_id, "randomized", card.get("allocation"), registry.get("allocation"),
                                           "high", "differs", () if ev.kind == "stated" else ("quote_not_found",), ev))
    return res
