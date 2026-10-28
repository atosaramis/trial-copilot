"""Plain-words labels and display context for the mismatch-check screen. Display only: the
numbers come from the saved results (app.cache.mismatch()); nothing is computed here beyond
picking labels and deciding which cards carry a "check this" flag."""
from __future__ import annotations

FIELD = {"sites": "Number of sites", "countries": "Number of countries", "enrollment": "Planned enrollment",
         "phase": "Phase", "randomized": "Randomized or not", "arms": "Number of arms"}
GAP = {"high": "large gap", "medium": "medium gap", "low": "small gap"}
AUTO = {
    "never_changed": ("The registry never changed", "The 2020 and 2023 records kept the 2017 value."),
    "caught_up": ("The registry later matched the protocol", "A later record reached the protocol's value, so the 2017 record was behind."),
    "partly_caught_up": ("The registry moved part of the way", "A later record moved toward the protocol but stayed short."),
    "registry_exceeded_protocol": ("The registry went past the protocol", "A later record moved beyond the protocol's value, so the two still disagree."),
    "changed_other_way": ("The registry moved away", "A later record changed, but not toward the protocol."),
    "ambiguous": ("The record can't settle this", "Our reading is doubtful, a later record is missing, or only an actual count remains."),
}
VERDICT = {"real_discrepancy": "The documents disagree", "registry_lagging": "The registry was behind the protocol",
           "extraction_error": "Our protocol reading was wrong", "ambiguous": "The agent can't tell"}
TRAP = {
    "upper_bound": "The protocol gives a maximum (\"up to\"), not a fixed number",
    "lower_bound": "The protocol gives a minimum (\"at least\")",
    "count_definition": "The registry's number matches a different count in the protocol (screened, completed, a stage)",
    "multi_part_design": "Multi-part design: how arms are counted is a convention",
    "other_study": "The only quote found is about another study",
    "satellite_sites": "The protocol counts satellite sites separately",
    "combined_phase": "The protocol gives a combined phase",
    "quote_not_found": "The number was not found in the protocol text",
    "registry_value_in_protocol": "The registry's number also appears in the protocol",
    "planning_assumption": "The number reads like a planning assumption",
    "registry_placeholder": "The 2017 registry value looks like a placeholder (1 site)",
    "evaluable_count": "The protocol number may be an evaluable count",
    "range": "The protocol gives a range",
}
AMBIGUOUS_REASON = {"trial finished before the next snapshot": "trials finished before the next record, so only an actual count remains",
                    "our protocol reading is doubtful": "doubtful readings of the protocol"}
DOUBTFUL_VERDICTS = {"extraction_error", "ambiguous"}


def _fmt(v):
    if v is None or v == "":
        return "not recorded"
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v)


def card(m: dict, url: str | None) -> dict:
    a = m.get("agent")
    why = [TRAP.get(t, t.replace("_", " ")) for t in m["traps"]]
    if m["auto"] == "ambiguous" and not m["traps"]:
        why.append("The registry history can't settle it")
    if a and a["verdict"] in DOUBTFUL_VERDICTS:
        why.append(f"Agent: {VERDICT[a['verdict']].lower()}")
    if a and a["agrees"] is False:
        why.append("The agent and the registry history disagree")
    prev, tl = None, []
    for t in m["timeline"]:
        tl.append({"year": t["year"], "value": _fmt(t["value"]), "changed": prev is not None and t["value"] != prev})
        prev = t["value"]
    page = (lambda n: f"{url}#page={n}") if url else (lambda n: None)
    return {
        "field": m["field"], "label": FIELD.get(m["field"], m["field"]), "gap": GAP.get(m["severity"], m["severity"]),
        "protocol": _fmt(m["protocol_value"]), "registry": _fmt(m["registry_value"]),
        "page": m["page"], "page_url": page(m["page"]) if m["page"] else None, "quote": m["quote"],
        "timeline": tl, "actual_note": any("(actual)" in t["value"] for t in tl), "auto": m["auto"], "auto_label": AUTO[m["auto"]][0], "auto_reason": AUTO[m["auto"]][1],
        "check": bool(why), "why": why,
        "agent": None if not a else {
            "verdict": a["verdict"], "label": VERDICT.get(a["verdict"], a["verdict"]), "explanation": a["explanation"],
            "citations": [dict(c, url=page(c["page"])) for c in a["citations"]], "dropped": a["dropped"],
            "agrees": a["agrees"]},
    }


def trial(t: dict) -> dict:
    cards = [card(m, t.get("protocol_url")) for m in t["mismatches"]]
    return {"nct": t["nct_id"], "label": t.get("label"), "title": t.get("title"), "url": t.get("protocol_url"),
            "cards": cards, "n_check": sum(c["check"] for c in cards),
            "compared": [{"label": FIELD.get(c["field"], c["field"]), "protocol": _fmt(c["protocol"]),
                          "registry": _fmt(c["registry_2017"]),
                          "differs": any(m["field"] == c["field"] for m in t["mismatches"])} for c in t["compared"]],
            "cleared": [{"label": FIELD.get(c["field"], c["field"]), "protocol": _fmt(c["protocol_value"]),
                         "registry": _fmt(c["registry_value"]), "why": "; ".join(TRAP.get(x, x) for x in c["traps"]),
                         "page": c["page"], "quote": c["quote"]} for c in t["cleared"]]}


def context(data: dict | None, nct: str | None) -> dict | None:
    if not data:
        return None
    demos = [trial(t) for t in data["demos"]]
    pick = next((d for d in demos if d["nct"] == nct), demos[0])
    return {"demos": demos, "trial": pick, "examples": [trial(t) for t in data["examples"]],
            "val": data["validation"], "rules": data.get("rules"),
            "ambiguous_reasons": [(n, AMBIGUOUS_REASON.get(k, k)) for k, n in
                                  (data["validation"]["scan"].get("ambiguous_reasons") or {}).items()]}
