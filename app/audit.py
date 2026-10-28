"""Search plus risk maths for one trial card (the middle of Tab 1).

`search_and_risk()` runs the step-by-step search, takes the chosen comparable and competing
sets, and hands them to the code-only risk maths. `audit_with_memo()` then has Muse Wonder write
the sponsor memo once from that output, and code checks it (app/memo.py).
"""
from __future__ import annotations

from pathlib import Path

from .agent import MODEL, run_search
from .memo import write_memo
from . import registry_risk
from .risk import assess
from .tools import RegistryTools


def search_and_risk(card: dict, nct_id: str | None = None, pools_dir=None, model: str = MODEL,
                    reasoning_effort: str = "minimal", client=None, raw_path: Path | None = None,
                    on_step=None) -> dict:
    tools = RegistryTools(pools_dir, exclude_nct=nct_id, target_enrollment=card.get("planned_enrollment"))
    reg = tools.registry_2017(nct_id) if nct_id else None
    search = run_search(card, tools, countries=(reg or {}).get("countries"), model=model,
                        reasoning_effort=reasoning_effort, client=client, raw_path=raw_path,
                        on_step=on_step)
    comp = tools.results.get(search["comparable_search"]) if search["comparable_search"] else None
    compet = tools.results.get(search["competing_search"]) if search["competing_search"] else None
    risk = assess(card, reg, comp, compet, tools.pool_totals())
    reg_full = tools.registry_2017(nct_id, include_criteria=True) if nct_id else None
    return {"search": search, "risk": risk, "registry_risk": registry_risk.assess(reg_full),
            "comparable": ({"result_id": search["comparable_search"], "args": comp["args"],
                            "nct_ids": comp["nct_ids"]} if comp else None),
            "competing": ({"result_id": search["competing_search"], "args": compet["args"],
                           "n": len(compet["nct_ids"])} if compet else None),
            "retrieved_nct_ids": sorted({i for r in tools.results.values() for i in r["nct_ids"]}),
            "registry_2017_used": {k: (str(v) if v is not None else None) for k, v in (reg or {}).items()
                                   if k in ("enrollment", "n_sites_2017", "start_date",
                                            "primary_completion_date", "countries")}}


def audit_with_memo(card: dict, nct_id: str | None = None, pools_dir=None, pages: dict | None = None,
                    card_flags: list | None = None, search_client=None, memo_client=None,
                    memo_effort: str = "medium") -> dict:
    """One audit: search, risk maths, then one checked memo."""
    out = search_and_risk(card, nct_id, pools_dir, client=search_client)
    out["memo"] = write_memo(card, out, pools_dir, nct_id, pages, card_flags, client=memo_client,
                             reasoning_effort=memo_effort)
    return out
