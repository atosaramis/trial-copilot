"""Display context for the primary-outcome triage view (saved results; no API call)."""
from __future__ import annotations

import datetime as dt
import math

KIND_LABEL = {"protocol": "Protocol", "amendment": "Amendment", "sap": "Analysis plan", "registry": "Registry",
              "results": "Results", "marker": "Date"}
TONE_LABEL = {"holds up": "Discrepancy requiring review", "probable": "Probable, needs a closer look"}
VERDICT_LABEL = {"needs_review": "Discrepancy requiring review", "timing_unsettled": "Timing can't be settled",
                 "possible_data_entry_error": "Possible data-entry error", "probable": "Probable, needs a closer look",
                 "explained": "Explained by the trial's documents"}
VERDICT_TONE = {"needs_review": "review", "timing_unsettled": "review", "possible_data_entry_error": "maybe",
                "probable": "maybe", "explained": "ok"}
GROUP_LABEL = {"holds_up": "Requires review", "probable": "Probable", "explained": "Explained", None: "Not in earlier review"}


def _d(s: str) -> dt.date:
    s = s.strip()
    return dt.date.fromisoformat(s if len(s) == 10 else s + "-01")


def nice_date(s: str | None) -> str:
    if not s:
        return "–"
    d = _d(s)
    return d.strftime("%b %-d, %Y") if len(s.strip()) == 10 else d.strftime("%b %Y")


def axis(events: list[dict]) -> list[dict]:
    """Horizontal timeline positions (percent) for each event, by date."""
    ds = [_d(e["date"]) for e in events]
    lo, hi = min(ds), max(ds)
    span = max(1, (hi - lo).days)
    out = []
    for i, (e, d) in enumerate(zip(events, ds)):
        pos = round(2 + 96 * (d - lo).days / span)
        edge = "edge-l" if pos < 8 else "edge-r" if pos > 92 else ""
        out.append({**e, "pos": pos, "row": i % 3, "edge": edge})
    return out


def years(events: list[dict]) -> list[dict]:
    ds = [_d(e["date"]) for e in events]
    lo, hi = min(ds), max(ds)
    span = max(1, (hi - lo).days)
    return [{"y": y, "pos": round(2 + 96 * (dt.date(y, 1, 1) - lo).days / span)}
            for y in range(lo.year + 1, hi.year + 1)]


def funnel(rows: list[dict]) -> list[dict]:
    top = math.log10(rows[0]["n"])
    total = 0.0
    out = []
    for r in rows:
        total += r["cost"]
        out.append({**r, "width": round(18 + 82 * math.log10(max(r["n"], 1)) / top), "running": round(total, 2)})
    return out


def context(data: dict | None) -> dict | None:
    if not data:
        return None
    cases = []
    for c in data["cases"]:
        cases.append({**c, "axis": axis(c["timeline"]), "years": years(c["timeline"])})
    return {"funnel": funnel(data["funnel"]), "triage": data["triage"], "spark": data["spark_calls"],
            "total_cost": data["total_cost"], "wonder_counts": data["wonder_counts"], "wonder_cost": data["wonder_cost"],
            "wonder_tokens": data["wonder_tokens"], "quotes": data["quotes"], "agreement": data["agreement"],
            "probable": data["probable"], "split": data["split"], "panel": data["panel"], "trimmed": data["trimmed"],
            "lead": next(c for c in cases if c["role"] == "lead"),
            "cleared": next(c for c in cases if c["role"] == "cleared"),
            "shortlist": data["shortlist"], "explained": data["explained"]}


GLOBALS = {"nice_date": nice_date, "kind_label": KIND_LABEL, "tone_label": TONE_LABEL, "verdict_label": VERDICT_LABEL,
           "verdict_tone": VERDICT_TONE, "group_label": GROUP_LABEL}
