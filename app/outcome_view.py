"""Display context for the primary-outcome triage view (saved results; no API call)."""
from __future__ import annotations

import datetime as dt
import math

KIND_LABEL = {"protocol": "Protocol", "amendment": "Amendment", "sap": "Analysis plan", "registry": "Registry",
              "results": "Results", "marker": "Date"}
TONE_LABEL = {"holds up": "Discrepancy requiring review", "probable": "Probable, needs a closer look"}


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
            "review": data["review"], "total_cost": data["total_cost"],
            "lead": next(c for c in cases if c["role"] == "lead"),
            "cleared": next(c for c in cases if c["role"] == "cleared"),
            "shortlist": data["shortlist"], "explained": data["explained"]}


GLOBALS = {"nice_date": nice_date, "kind_label": KIND_LABEL, "tone_label": TONE_LABEL}
