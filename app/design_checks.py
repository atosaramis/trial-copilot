"""Code checks on the design numbers the text call read (run after merge_card, no model call).

Patterns found when Muse Wonder and Argon re-read disputed mismatch rows against full protocols:

- enrollment: two places in the protocol giving different planned totals (synopsis 102, body 90)
  is an internal inconsistency. Both values are kept in `planned_enrollment_values` and
  planned_enrollment is left empty, so nothing downstream silently picks one. Each value must
  appear on the page the model cited, or it is dropped.
- enrollment: a total that appears only next to "complete"/"evaluable" wording is flagged.
- arms: a protocol that calls itself single-arm / single-group (outside a background or
  prior-study passage) has one arm, whatever the dose cohorts.
- sites: a site count that appears only inside a planning or statistical assumption
  ("accrual estimates assume 40 enrollment sites") is not the planned site count.
"""
from __future__ import annotations

import re

from .mismatch.finder import ASSUMPTION_RX, PERSON_RX_V3, PRIOR_RX, SITE_RX_V3, _hits, _tok

SINGLE_ARM_RX = re.compile(r"\bsingle[- ](?:arm|group)\b|\bone[- ]arm\b|\bsingle[- ]cohort\b", re.I)
SITE_ASSUMPTION_RX = re.compile(ASSUMPTION_RX.pattern + r"|statistical planning|estimates? of accrual|for planning purposes",
                                re.I)
RANDOMIZED_RX = re.compile(r"(?<!non-)(?<!non)(?<!non )randomi[sz]", re.I)
SENT_END = re.compile(r"[.;:!?](?:\s|$)")


def _flat(pages: list[str] | None) -> list[str]:
    return [re.sub(r"\s+", " ", p) for p in (pages or [])]


def _sentence(t: str, a: int, b: int) -> str:
    """The sentence around t[a:b] (bounded by sentence punctuation, at most 300 chars each side)."""
    lo = max(0, a - 300)
    pre = [m.end() for m in SENT_END.finditer(t, lo, a)]
    start = pre[-1] if pre else lo
    post = SENT_END.search(t, b, min(len(t), b + 300))
    return t[start: post.start() + 1 if post else min(len(t), b + 300)]


def _num_on_page(n: int, page: str) -> bool:
    return re.search(rf"(?<![\d,.]){n:,}(?![\d,])|(?<![\d,.]){n}(?![\d,])", page) is not None


def _int(x):
    try:
        return int(round(float(str(x).replace(",", ""))))
    except (TypeError, ValueError):
        return None


def enrollment_totals(text_out: dict, pages: list[str]) -> list[dict]:
    """Planned totals the model says the protocol states, kept only if the number is on the cited page."""
    out = []
    for t in text_out.get("planned_enrollment_totals_stated") or []:
        if not isinstance(t, dict):
            continue
        n, pg = _int(t.get("n")), _int(t.get("page"))
        if not n or n <= 0:
            continue
        if pages and not (pg and 1 <= pg <= len(pages) and _num_on_page(n, pages[pg - 1])):
            continue
        out.append({"n": n, "page": pg, "where": str(t.get("where") or "")[:60]})
    return out


def apply(card: dict, cites: dict, source: dict, flags: list, text_out: dict, pages: list[str] | None) -> dict:
    """Adjust card in place; returns it. `pages`: protocol text per PDF page (None for scans)."""
    flat = _flat(pages)
    card["planned_enrollment_values"] = []

    # 1. Enrollment: different planned totals in different places -> report both, pick neither.
    totals = enrollment_totals(text_out, flat)
    values = sorted({t["n"] for t in totals})
    if len(values) >= 2:
        card["planned_enrollment_values"] = values
        old = card.get("planned_enrollment")
        card["planned_enrollment"] = None
        source["planned_enrollment"] = "code"
        source["planned_enrollment_values"] = "code"
        cites["planned_enrollment_values"] = sorted({t["page"] for t in totals if t["page"]})
        cites.pop("planned_enrollment", None)
        flags.append("planned_enrollment: internal protocol inconsistency, different planned totals stated: "
                     + "; ".join(f"{t['n']} ({t['where'] or 'p.'} p.{t['page']})" for t in totals)
                     + f"; none picked (text call read {old})")
    elif flat and card.get("planned_enrollment"):
        # 2. Enrollment read from a completers/evaluable sentence only: flag it.
        p = card["planned_enrollment"]
        hits = [h for h in _hits(flat, PERSON_RX_V3) if p in (h.low, h.high)]
        if hits and all(h.role == "completed" or h.evaluable for h in hits):
            flags.append(f"planned_enrollment: {p} appears only as a completed/evaluable count; check the enrolled total")

    # 3. Arms: a protocol that calls itself single-arm but was read as several arms.
    # Advisory only. The prompt already folds dose levels and sequential cohorts into one
    # arm; parallel cohorts of different patient groups (one drug, two populations) are
    # counted as separate groups by the registry, so code does not override the count.
    n = card.get("n_arms")
    if n and n > 1 and flat:
        for i, t in enumerate(flat, start=1):
            m = next((m for m in SINGLE_ARM_RX.finditer(t)
                      if not PRIOR_RX.search(t[max(0, m.start() - 150): m.end() + 80])
                      and not RANDOMIZED_RX.search(_sentence(t, m.start(), m.end()))), None)
            if m:
                flags.append(f"n_arms: read {n} but the protocol calls itself single-arm (p.{i}); "
                             "check whether the cohorts are dose levels within one arm")
                break

    # 4. Sites: a count stated only inside a planning/statistical assumption is not the plan.
    s = card.get("planned_sites")
    if s and flat:
        hits = []
        for i, t in enumerate(flat, start=1):
            for rx in SITE_RX_V3:
                for m in rx.finditer(t):
                    try:
                        vals = {_tok(m.group(1)), _tok(m.group(2)) if m.lastindex and m.lastindex >= 2 else None}
                    except (ValueError, IndexError):
                        continue
                    if s in vals:
                        hits.append((i, bool(SITE_ASSUMPTION_RX.search(_sentence(t, m.start(), m.end())))))
        if hits and all(a for _, a in hits):
            card["planned_sites"] = None
            source["planned_sites"] = "code"
            cites.pop("planned_sites", None)
            flags.append(f"planned_sites: {s} appears only in a planning/statistical assumption "
                         f"(p.{hits[0][0]}); not taken as the planned site count")
    return card
