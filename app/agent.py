"""The step-by-step past-trial search (build spec sections 2.3, 3 and 5).

Muse Spark 1.3 calls the DuckDB tools in `app/tools.py`, at most `MAX_STEPS` (6) tool calls,
then a hard stop: if it still wants to search, code ends the loop and uses the cohort it has,
flagged "search capped". Every step is logged (tool, arguments, the model's one-line reason,
rows returned), which is what the UI streams as the search trace.

What the model sees: the trial card's design fields (no NCT ID, so it can't recall how the real
trial ended) and, when known, the countries in the trial's Jan 2017 registry record. The tools
return Jan 2017 data only.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from .tools import TOOL_SPECS, RegistryTools, ToolError

BASE_URL = "https://api.meta.ai/v1"
MODEL = "muse-spark-1.3"
MAX_STEPS = 6
MAX_TURNS = MAX_STEPS + 2
MIN_COHORT = 10
PRICES = {  # USD per token: input, output, cached input
    "muse-spark-1.3": (1.25e-6, 4.25e-6, 0.15e-6),
    "muse-spark-1.3-contributor": (0.10e-6, 0.20e-6, 0.10e-6),
}
PROMPT = Path(__file__).parent / "prompts" / "search_agent.txt"
CARD_KEYS = ["condition", "interventions", "phase", "planned_enrollment", "n_arms", "allocation",
             "masking", "placebo_arm", "min_age_years", "max_age_years", "sponsor_type",
             "planned_countries", "planned_sites", "enrollment_period_months", "required_biomarker",
             "max_prior_lines", "performance_status_requirement", "brain_mets_allowed"]


class SearchError(RuntimeError):
    pass


def cost_usd(usage: dict | None, model: str) -> float:
    if not usage:
        return 0.0
    pin_rate, pout_rate, pcached_rate = PRICES.get(model, PRICES[MODEL])
    cached = ((usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
    return round((usage.get("prompt_tokens", 0) - cached) * pin_rate + cached * pcached_rate
                 + usage.get("completion_tokens", 0) * pout_rate, 6)


def card_brief(card: dict, countries: str | None = None) -> str:
    brief = {k: card.get(k) for k in CARD_KEYS if card.get(k) not in (None, "", [])}
    if countries:
        brief["countries_in_registry_record_jan_2017"] = countries
    return json.dumps(brief, ensure_ascii=False, indent=1)


def _client():
    from openai import OpenAI
    key = os.environ.get("META_API_KEY")
    if not key:
        raise SearchError("META_API_KEY is not set in the environment")
    return OpenAI(base_url=BASE_URL, api_key=key, timeout=180, max_retries=0)


def _parse_final(content: str | None) -> dict | None:
    if not content:
        return None
    m = re.search(r"\{.*\}", content, re.S)
    if not m:
        return None
    try:
        out = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return out if isinstance(out, dict) else None


def _result_summary(res: dict) -> dict:
    """What the trace shows for one tool result (not the full rows)."""
    if "n_matched" in res:
        return {"result_id": res["result_id"], "rows": res["n_matched"],
                "outcome_counts_2017": res["outcome_counts_2017"]}
    if "n_recruiting" in res:
        return {"result_id": res["result_id"], "rows": res["n_recruiting"], "total_sites": res["total_sites"]}
    return {"result_id": res.get("result_id"), "rows": 0 if res.get("found") is False else 1}


def choose(tools: RegistryTools, final: dict | None, flags: list) -> tuple[str | None, str | None]:
    """Validate the model's picks; fall back to code's pick when they don't hold up."""
    comp = (final or {}).get("comparable_search")
    compet = (final or {}).get("competing_search")
    res = tools.results
    if not (comp in res and res[comp]["tool"] == "search_comparable_trials"
            and len(res[comp]["nct_ids"]) >= MIN_COHORT):
        searches = [k for k, v in res.items() if v["tool"] == "search_comparable_trials"]
        good = [k for k in searches if len(res[k]["nct_ids"]) >= MIN_COHORT]
        pick = good[-1] if good else (max(searches, key=lambda k: len(res[k]["nct_ids"])) if searches else None)
        if comp is not None or final is not None:
            flags.append(f"model's comparable pick {comp!r} not usable; code used {pick}")
        comp = pick
    if not (compet in res and res[compet]["tool"] == "count_competing_trials"):
        comps = [k for k, v in res.items() if v["tool"] == "count_competing_trials"]
        compet = comps[-1] if comps else None
    return comp, compet


def run_search(card: dict, tools: RegistryTools, countries: str | None = None,
               model: str = MODEL, reasoning_effort: str = "minimal", max_steps: int = MAX_STEPS,
               client=None, raw_path: Path | None = None, on_step=None) -> dict:
    """Run the tool loop. Returns the trace, the chosen result ids, usage and cost."""
    client = client or _client()
    system = PROMPT.read_text().replace("{max_steps}", str(max_steps))
    messages: list = [{"role": "system", "content": system},
                      {"role": "user", "content": "Trial card (from the draft protocol):\n" + card_brief(card, countries)}]
    steps: list[dict] = []
    turns: list[dict] = []
    flags: list[str] = []
    used = 0
    capped = False
    final = None
    nudged = False
    raw = open(raw_path, "w") if raw_path else None
    t_start = time.time()
    try:
        for _turn in range(MAX_TURNS):
            out_of_budget = used >= max_steps
            kwargs = dict(model=model, messages=messages, tools=TOOL_SPECS,
                          reasoning_effort=reasoning_effort, max_completion_tokens=3000)
            if out_of_budget and not nudged:
                # Muse accepts only tool_choice "auto", so the stop is a message plus code refusing
                # any further calls (they come back "not run: search capped").
                messages.append({"role": "user", "content": f"Tool budget used ({max_steps} of {max_steps}). "
                                 "Do not call any more tools. Reply now with the final JSON only."})
                nudged = True
            t0 = time.time()
            try:
                resp = client.chat.completions.create(**kwargs)
            except Exception as e:  # noqa: BLE001 - recorded, then raised so the caller can inspect it
                err = f"{type(e).__name__}: {getattr(e, 'status_code', '')} {str(e)[:400]}"
                if raw:
                    raw.write(json.dumps({"error": err}) + "\n")
                raise SearchError(err) from e
            d = resp.model_dump()
            if raw:
                raw.write(json.dumps(d, default=str) + "\n")
            usage = d.get("usage") or {}
            turns.append({"latency_s": round(time.time() - t0, 1), "usage": usage,
                          "cost_usd": cost_usd(usage, model),
                          "finish_reason": d["choices"][0].get("finish_reason")})
            msg = resp.choices[0].message
            calls = msg.tool_calls or []
            if not calls:
                final = _parse_final(msg.content)
                if final is None:
                    flags.append("final reply was not the expected JSON; code picked the cohort")
                break
            messages.append(msg.model_dump(exclude_none=True))
            for tc in calls:
                step = {"step": len(steps) + 1, "tool": tc.function.name}
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = None
                step["args"] = {k: v for k, v in (args or {}).items() if k != "reason"}
                step["reason"] = (args or {}).get("reason")
                if used >= max_steps:
                    capped = True
                    payload = {"error": f"tool budget used ({max_steps} of {max_steps}); reply with the final JSON now"}
                    step["status"] = "not run: search capped"
                else:
                    used += 1
                    t1 = time.time()
                    try:
                        if args is None:
                            raise ToolError("arguments were not valid JSON")
                        res = tools.call(tc.function.name, args)
                        payload = res
                        step.update(_result_summary(res), status="ok")
                    except ToolError as e:
                        payload = {"error": str(e)}
                        step.update(status="tool error", error=str(e))
                    step["tool_latency_s"] = round(time.time() - t1, 2)
                steps.append(step)
                if on_step:
                    on_step(step)
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": json.dumps(payload, default=str, ensure_ascii=False)})
        else:
            capped = True
    finally:
        if raw:
            raw.close()
    if capped:
        flags.append("search capped")
    comp, compet = choose(tools, final, flags)
    if compet is None and comp is not None:
        # The model never counted competing trials: code runs the obvious count once, flagged.
        a = tools.results[comp]["args"]
        res = tools.count_competing_trials(a["condition_terms"], a.get("phase") or None)
        compet = res["result_id"]
        flags.append(f"competing trials counted by code ({compet}) with the chosen search's condition and phase")
    usage_tot = {"prompt_tokens": sum(t["usage"].get("prompt_tokens", 0) for t in turns),
                 "completion_tokens": sum(t["usage"].get("completion_tokens", 0) for t in turns),
                 "reasoning_tokens": sum(((t["usage"].get("completion_tokens_details") or {})
                                          .get("reasoning_tokens") or 0) for t in turns)}
    return {"model": model, "reasoning_effort": reasoning_effort, "max_steps": max_steps,
            "steps": steps, "tool_calls_used": used, "capped": capped,
            "model_final": final, "summary": (final or {}).get("summary"), "comparable_search": comp, "competing_search": compet,
            "flags": flags, "turns": turns, "usage": usage_tot,
            "cost_usd": round(sum(t["cost_usd"] for t in turns), 6),
            "latency_s": round(time.time() - t_start, 1)}
