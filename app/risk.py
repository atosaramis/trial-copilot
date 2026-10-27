"""Enrollment-risk maths. Code only, no model: every number here is "computed, not guessed".

Build spec section 2, step 4:
- the share of comparable trials stopped for poor enrollment (n/N with a Wilson 95% interval),
  next to the rate across the whole Jan 2017 pool;
- patients each site must enroll per month: planned N / (sites x enrollment months), with sites
  from the protocol first and the Jan 2017 registry count as the fallback (never a later one);
- how that per-site pace compares with what comparable completed trials actually achieved;
- the number of competing trials open in Jan 2017;
- what-if: `what_if()` recomputes the pace for any sites/months. The browser does the same sums
  from `slider_model()` (no model call on a slider drag).

Nothing here predicts whether a given trial will stop. It describes base rates and arithmetic.
"""
from __future__ import annotations

import math
from datetime import date, datetime

Z95 = 1.959963984540054
N_QUANTILES = 101  # 0th..100th percentile of the comparable pace distribution


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float] | tuple[None, None]:
    """Wilson score 95% interval for k events out of n."""
    if not n:
        return (None, None)
    if k < 0 or k > n:
        raise ValueError("k must be between 0 and n")
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, centre - half), min(1.0, centre + half))


def rate_block(k: int, n: int) -> dict:
    lo, hi = wilson(k, n)
    return {"events": k, "n": n, "rate": (k / n) if n else None, "ci95": [lo, hi]}


def months_between(start, end) -> float | None:
    """Calendar months from start to end (30.44-day months); None if either is missing or end <= start."""
    def _d(x):
        if x is None:
            return None
        if isinstance(x, datetime):
            return x.date()
        if isinstance(x, date):
            return x
        try:
            return date.fromisoformat(str(x)[:10])
        except ValueError:
            return None
    a, b = _d(start), _d(end)
    if not a or not b or b <= a:
        return None
    return (b - a).days / 30.44


def pace(planned_n, sites, months) -> float | None:
    """Patients each site must enroll per month."""
    try:
        n, s, m = float(planned_n), float(sites), float(months)
    except (TypeError, ValueError):
        return None
    if n <= 0 or s <= 0 or m <= 0:
        return None
    return n / (s * m)


def achieved_paces(rows) -> list[float]:
    """Per-site monthly pace that comparable COMPLETED trials actually achieved, from their Jan 2017
    record: actual enrollment / (sites x months from start to primary completion). Months include
    treatment and follow-up after the last patient, so this understates their true enrollment speed;
    the plan is put on the same basis before comparing (see `assess`)."""
    out = []
    for r in rows:
        if r.get("outcome_2017") != "completed":
            continue
        p = pace(r.get("enrollment"), r.get("n_sites_2017"),
                 months_between(r.get("start_date"), r.get("primary_completion_date")))
        if p is not None:
            out.append(p)
    return sorted(out)


def quantiles(sorted_vals: list[float], k: int = N_QUANTILES) -> list[float]:
    """k evenly spaced quantiles (linear interpolation), for the browser's slider maths."""
    if not sorted_vals:
        return []
    n = len(sorted_vals)
    out = []
    for i in range(k):
        pos = (n - 1) * i / (k - 1)
        lo = math.floor(pos)
        hi = min(lo + 1, n - 1)
        out.append(sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo))
    return out


def share_at_least(q: list[float], value: float | None) -> float | None:
    """Share of comparable completed trials whose achieved pace was >= value, read off the
    quantile table (the same sum the browser does)."""
    if value is None or not q:
        return None
    if value <= q[0]:
        return 1.0
    if value > q[-1]:
        return 0.0
    k = len(q)
    for i in range(1, k):
        if value <= q[i]:
            span = q[i] - q[i - 1]
            frac = (value - q[i - 1]) / span if span > 0 else 1.0
            below = (i - 1 + frac) / (k - 1)
            return round(1.0 - below, 4)
    return 0.0


def what_if(planned_n, sites, months, pace_quantiles: list[float], months_basis_offset: float = 0.0) -> dict:
    """Recompute the pace for a slider position. `months_basis_offset` adds the months the
    comparison basis includes beyond enrollment (0 when both use start-to-primary-completion)."""
    p = pace(planned_n, sites, months)
    p_cmp = pace(planned_n, sites, (months or 0) + months_basis_offset) if months else None
    return {"sites": sites, "months": months, "patients_per_site_per_month": p,
            "share_of_completed_comparables_at_least_this_fast": share_at_least(pace_quantiles, p_cmp)}


def assess(card: dict, registry_2017: dict | None, comparable: dict | None, competing: dict | None,
           pool_totals: dict) -> dict:
    """All risk numbers for one audit.

    card: the trial card. registry_2017: the trial's own Jan 2017 registry record, or None for an
    upload. comparable: {"nct_ids", "outcome_counts", "rows"} of the chosen comparable search.
    competing: {"nct_ids", "rows"} of the chosen competing search. pool_totals: {"n", "events"}.
    """
    reg = registry_2017 or {}
    flags: list[str] = []
    planned_n = card.get("planned_enrollment")
    n_src = "protocol"
    if not planned_n and reg.get("enrollment"):
        planned_n, n_src = reg["enrollment"], "registry_2017"
    sites, s_src = card.get("planned_sites"), "protocol"
    if not sites and reg.get("n_sites_2017"):
        sites, s_src = reg["n_sites_2017"], "registry_2017"
    if card.get("planned_sites") and reg.get("n_sites_2017") and card["planned_sites"] != reg["n_sites_2017"]:
        flags.append(f"sites: protocol says {card['planned_sites']}, Jan 2017 registry lists "
                     f"{reg['n_sites_2017']}; the protocol figure is used (try the other on the slider)")
    reg_months = months_between(reg.get("start_date"), reg.get("primary_completion_date"))
    months, m_src = card.get("enrollment_period_months"), "protocol enrollment period"
    if not months and reg_months:
        months, m_src = round(reg_months, 1), "registry_2017 start to planned primary completion"
        flags.append("months: the protocol states no enrollment period, so the Jan 2017 registry's "
                     "start-to-planned-primary-completion span is used (includes follow-up, so the "
                     "pace shown is a floor)")
    p = pace(planned_n, sites, months)

    # Comparable trials: base rate next to the whole pool.
    comp_block = None
    pace_q: list[float] = []
    if comparable and comparable.get("nct_ids"):
        oc = comparable.get("outcome_counts") or {}
        n = len(comparable["nct_ids"])
        comp_block = rate_block(int(oc.get("terminated_poor_enrollment", 0)), n)
        comp_block["outcome_counts"] = oc
        pace_q = quantiles(achieved_paces(comparable.get("rows") or []))
        comp_block["completed_with_pace"] = len(achieved_paces(comparable.get("rows") or []))
    pool_block = rate_block(int(pool_totals.get("events", 0)), int(pool_totals.get("n", 0)))
    if comp_block and comp_block["n"] < 30:
        flags.append(f"only {comp_block['n']} comparable trials: the interval is wide")

    # Put the plan on the same basis as the comparables (start to primary completion) when the
    # registry gives that span; otherwise compare the enrollment-period pace and say so.
    offset = 0.0
    if m_src == "protocol enrollment period" and reg_months and months and reg_months > months:
        offset = reg_months - months
    elif m_src == "protocol enrollment period":
        flags.append("pace comparison uses the protocol's enrollment period against comparables' "
                     "start-to-primary-completion spans, so it leans pessimistic")
    p_cmp = pace(planned_n, sites, (months or 0) + offset) if months else None
    share = share_at_least(pace_q, p_cmp)

    comp_trials = None
    if competing is not None:
        rows = competing.get("rows") or []
        comp_trials = {"n_recruiting_jan_2017": len(competing.get("nct_ids") or []),
                       "total_sites": int(sum((r.get("n_sites_2017") or 0) for r in rows)),
                       "args": competing.get("args")}
    return {
        "label": "computed, not guessed",
        "comparable_trials": comp_block,
        "all_trials_in_pool": pool_block,
        "relative_to_pool": (round(comp_block["rate"] / pool_block["rate"], 2)
                             if comp_block and comp_block["rate"] is not None and pool_block["rate"] else None),
        "site_pace": {
            "planned_enrollment": planned_n, "planned_enrollment_source": n_src,
            "sites": sites, "sites_source": s_src, "registry_sites_2017": reg.get("n_sites_2017"),
            "months": months, "months_source": m_src,
            "patients_per_site_per_month": p,
            "comparable_completed_median_pace": pace_q[50] if pace_q else None,
            "comparable_completed_iqr": [pace_q[25], pace_q[75]] if pace_q else None,
            "share_of_completed_comparables_at_least_this_fast": share,
        },
        "competing_trials": comp_trials,
        "slider_model": {"planned_enrollment": planned_n, "sites": sites, "months": months,
                         "months_basis_offset": round(offset, 2), "pace_quantiles": pace_q},
        "flags": flags,
    }
