"""Muse investigation agent: one run per trial, covering every mismatch the finder flagged.

The model reads protocol pages and the registry history through three local tools ($0 each).
It returns one verdict per mismatch with citations. Code then checks every protocol quote
against the PDF text and every registry value against the snapshots, and drops any claim it cannot
support. A verdict left with no supporting evidence becomes "ambiguous".

Limits: at most MAX_STEPS tool calls and MAX_PROMPT_TOKENS prompt tokens per trial, and a
spend ledger with a hard cap that is checked before every call. Muse accepts only tool_choice
"auto", so the stop is a "budget used" message, and code refuses any further tool calls.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict
from pathlib import Path

from ..agent import cost_usd, PRICES
from .autograde import Snapshot
from .finder import Mismatch, normalize_phase, registry_randomized
from .ledger import SpendLedger

PROMPT = Path(__file__).resolve().parents[1] / "prompts" / "mismatch_agent.txt"
VERDICTS = ("real_discrepancy", "registry_lagging", "extraction_error", "ambiguous")
MAX_STEPS = 6
MAX_PROMPT_TOKENS = 120_000      # summed over the trial's turns
MAX_COMPLETION = 2500            # per turn
MAX_PAGES_PER_CALL = 3
PAGE_CHARS = 3500
SNAP_FIELD = {"sites": "n_sites", "countries": "n_countries", "enrollment": "enrollment", "arms": "n_arms",
              "phase": "phase", "randomized": "allocation"}

TOOL_SPECS = [
    {"type": "function", "function": {
        "name": "read_pages", "description": "Read up to 3 protocol pages (PDF page numbers).",
        "parameters": {"type": "object", "properties": {
            "pages": {"type": "array", "items": {"type": "integer"}}}, "required": ["pages"]}}},
    {"type": "function", "function": {
        "name": "search_protocol",
        "description": "Find a word or phrase (case-insensitive) in the whole protocol. Returns up to 8 pages with snippets.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "get_registry_history",
        "description": "Registry value of one field in the Jan 2017, Jan 2020 and Jan 2023 versions.",
        "parameters": {"type": "object", "properties": {
            "field": {"type": "string", "enum": list(SNAP_FIELD)}}, "required": ["field"]}}},
]


class AgentError(RuntimeError):
    pass


def norm_text(s: str) -> str:
    s = s.lower().replace("ﬁ", "fi").replace("ﬂ", "fl")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _page_list(v) -> list[int]:
    """Page numbers from a list, a single number, or a string like "[28, 29]" (some models send that)."""
    if isinstance(v, (int, float)):
        return [int(v)]
    if isinstance(v, str):
        return [int(x) for x in re.findall(r"\d+", v)]
    return [int(x) for x in (v or []) if str(x).strip().isdigit()]


class TrialTools:
    """Local tools over one trial's protocol text and registry snapshots."""

    def __init__(self, pages: list[str], snapshots: dict[str, Snapshot]):
        self.pages, self.snapshots = pages, snapshots          # snapshots keyed "2017", "2020", "2023"
        self.read: set[int] = set()
        self._norm = [norm_text(p) for p in pages]

    def call(self, name: str, args: dict) -> dict:
        if name == "read_pages":
            want = _page_list(args.get("pages"))[:MAX_PAGES_PER_CALL]
            if not self.pages:
                return {"error": "this protocol has no usable text layer"}
            out = []
            for p in want:
                if 1 <= p <= len(self.pages):
                    self.read.add(p)
                    out.append({"page": p, "text": self.pages[p - 1][:PAGE_CHARS]})
            return {"pages": out, "n_pages_in_protocol": len(self.pages)}
        if name == "search_protocol":
            q = str(args.get("query") or "").strip()
            if len(q) < 2:
                return {"error": "query too short"}
            hits = []
            for i, t in enumerate(self.pages, start=1):
                for m in re.finditer(re.escape(q), t, re.I):
                    hits.append({"page": i, "snippet": t[max(0, m.start() - 120): m.end() + 120]})
                    self.read.add(i)
                    break
                if len(hits) >= 8:
                    break
            return {"query": q, "hits": hits}
        if name == "get_registry_history":
            f = args.get("field")
            if f not in SNAP_FIELD:
                return {"error": f"unknown field {f!r}"}
            out = {}
            for k, s in sorted(self.snapshots.items()):
                v = getattr(s, SNAP_FIELD[f])
                out[k] = v
                if f == "enrollment":
                    out[k + "_type"] = s.enrollment_type
            return {"field": f, "values": out}
        return {"error": f"unknown tool {name!r}"}

    # ---------- verification ----------
    def quote_ok(self, page, quote) -> int | None:
        """Page where the quote really is (the cited page first, then +-1), or None."""
        q = norm_text(str(quote or ""))
        if len(q.split()) < 4:
            return None
        try:
            p = int(page)
        except (TypeError, ValueError):
            p = 0
        for cand in (p, p - 1, p + 1):
            if 1 <= cand <= len(self._norm) and q in self._norm[cand - 1]:
                return cand
        return None

    def registry_ok(self, snapshot, field, value) -> bool:
        s = self.snapshots.get(str(snapshot)[:4])
        if s is None or field not in SNAP_FIELD:
            return False
        true = getattr(s, SNAP_FIELD[field])
        if true is None:
            return value in (None, "", "null")
        if field == "phase":
            return normalize_phase(str(value)) == normalize_phase(true)
        if field == "randomized":
            return registry_randomized(str(value)) == registry_randomized(true) or str(value).strip().lower() == str(true).lower()
        try:
            return float(value) == float(true)
        except (TypeError, ValueError):
            return False


def verify(findings: list, mismatches: list[Mismatch], tools: TrialTools) -> list[dict]:
    """One checked finding per mismatch. Unsupported citations are dropped; a verdict with no
    supporting protocol quote (or, for registry_lagging, no checked later registry value) becomes ambiguous."""
    by_field = {}
    for f in findings or []:
        if isinstance(f, dict) and f.get("field") in SNAP_FIELD and f["field"] not in by_field:
            by_field[f["field"]] = f
    out = []
    for m in mismatches:
        f = by_field.get(m.field)
        rec = {"field": m.field, "protocol_value_card": m.protocol_value, "registry_value_2017": m.registry_value,
               "severity": m.severity, "traps": list(m.traps), "model_verdict": None, "verdict": "ambiguous",
               "explanation": "", "protocol_citations": [], "registry_citations": [], "dropped": [], "checks": []}
        if f is None:
            rec["checks"].append("model gave no finding for this field")
            out.append(rec)
            continue
        v = f.get("verdict") if f.get("verdict") in VERDICTS else None
        rec["model_verdict"] = f.get("verdict")
        rec["explanation"] = str(f.get("explanation") or "")[:600]
        rec["model_protocol_value"] = f.get("protocol_value")
        for c in f.get("protocol_citations") or []:
            if not isinstance(c, dict):
                continue
            pg = tools.quote_ok(c.get("page"), c.get("quote"))
            if pg is None:
                rec["dropped"].append({"kind": "quote", **c})
            else:
                rec["protocol_citations"].append({"page": pg, "quote": str(c.get("quote"))[:400],
                                                  **({"page_corrected_from": c.get("page")} if pg != c.get("page") else {})})
        for c in f.get("registry_citations") or []:
            if not isinstance(c, dict):
                continue
            fld = c.get("field") or m.field
            if tools.registry_ok(c.get("snapshot"), fld, c.get("value")):
                rec["registry_citations"].append({"snapshot": str(c.get("snapshot"))[:4], "field": fld, "value": c.get("value")})
            else:
                rec["dropped"].append({"kind": "registry", **c})
        if v is None:
            rec["checks"].append(f"verdict {f.get('verdict')!r} is not one of the four")
        elif v != "ambiguous" and not rec["protocol_citations"]:
            rec["checks"].append(f"{v} had no quote code could find in the protocol; set to ambiguous")
        elif v == "registry_lagging" and not any(c["snapshot"] in ("2020", "2023") for c in rec["registry_citations"]):
            rec["checks"].append("registry_lagging had no checked 2020/2023 registry value; set to ambiguous")
        else:
            rec["verdict"] = v
        out.append(rec)
    return out


def brief(mismatches: list[Mismatch], card_pages: dict | None, n_pages: int, has_text: bool) -> str:
    rows = []
    for m in mismatches:
        rows.append({"field": m.field, "protocol_value_extracted": m.protocol_value,
                     "registry_value_jan_2017": m.registry_value,
                     "page_found_by_code": m.evidence.page, "code_quote": m.evidence.quote,
                     "pages_cited_by_extraction": (card_pages or {}).get(
                         {"sites": "planned_sites", "countries": "planned_countries", "enrollment": "planned_enrollment",
                          "arms": "n_arms", "phase": "phase", "randomized": "allocation"}[m.field]),
                     "code_flags": list(m.traps)})
    head = f"The protocol has {n_pages} pages." + ("" if has_text else " It has NO usable text layer: the tools cannot read it.")
    return head + "\nDisagreements to investigate:\n" + json.dumps(rows, ensure_ascii=False, indent=1, default=str)


def _estimate(messages, model) -> float:
    pin, pout, _ = PRICES[model]
    est_in = len(json.dumps(messages, default=str)) / 3.0 + 1500     # chars/3 over-counts tokens; +tool specs
    return est_in * pin + MAX_COMPLETION * pout


def _parse(content):
    m = re.search(r"\{.*\}", content or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return d if isinstance(d, dict) else None


def investigate(nct_id: str, mismatches: list[Mismatch], tools: TrialTools, ledger: SpendLedger, client,
                model: str, reasoning_effort: str = "minimal", card_pages: dict | None = None,
                max_steps: int = MAX_STEPS, raw_path: Path | None = None, run_tag: str = "") -> dict:
    system = PROMPT.read_text().replace("{max_steps}", str(max_steps))
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": brief(mismatches, card_pages, len(tools.pages) or 0, bool(tools.pages))}]
    used, nudged, prompt_tokens, turns, steps, flags, final = 0, False, 0, [], [], [], None
    raw = open(raw_path, "w") if raw_path else None
    t0 = time.time()
    try:
        for _ in range(max_steps + 3):
            stop = used >= max_steps or prompt_tokens >= MAX_PROMPT_TOKENS
            if stop and not nudged:
                messages.append({"role": "user", "content": "Budget used. Do not call any more tools. "
                                                            "Reply now with the final JSON only."})
                nudged = True
            elif stop and nudged and turns and turns[-1].get("tool_calls"):
                flags.append("model kept calling tools after the budget message")
                break
            est = _estimate(messages, model)
            held = ledger.reserve(est, f"{nct_id} turn {len(turns) + 1}")
            t1 = time.time()
            try:
                resp = client.chat.completions.create(model=model, messages=messages, tools=TOOL_SPECS,
                                                      reasoning_effort=reasoning_effort,
                                                      max_completion_tokens=MAX_COMPLETION)
            except Exception as e:  # noqa: BLE001
                ledger.record(held, 0.0, nct_id=nct_id, model=model, run=run_tag, status="error", note=str(e)[:200])
                raise AgentError(f"{type(e).__name__}: {getattr(e, 'status_code', '')} {str(e)[:300]}") from e
            d = resp.model_dump()
            usage = d.get("usage") or {}
            c = cost_usd(usage, model)
            ledger.record(held, c, nct_id=nct_id, model=model, run=run_tag, status="ok",
                          prompt_tokens=usage.get("prompt_tokens"), completion_tokens=usage.get("completion_tokens"))
            if raw:
                raw.write(json.dumps(d, default=str) + "\n")
            prompt_tokens += usage.get("prompt_tokens") or 0
            msg = resp.choices[0].message
            calls = msg.tool_calls or []
            turns.append({"latency_s": round(time.time() - t1, 1), "usage": usage, "cost_usd": c,
                          "finish_reason": d["choices"][0].get("finish_reason"), "tool_calls": len(calls)})
            if not calls:
                final = _parse(msg.content)
                if final is None:
                    flags.append("final reply was not JSON")
                break
            messages.append(msg.model_dump(exclude_none=True))
            for tc in calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = None
                if used >= max_steps or prompt_tokens >= MAX_PROMPT_TOKENS:
                    payload, status = {"error": "budget used; reply with the final JSON now"}, "refused"
                elif args is None:
                    used += 1
                    payload, status = {"error": "arguments were not valid JSON"}, "bad args"
                else:
                    used += 1
                    try:
                        payload, status = tools.call(tc.function.name, args), "ok"
                    except Exception as e:          # bad arguments become a message, not a crash
                        payload, status = {"error": f"tool failed on these arguments: {type(e).__name__}"}, "tool error"
                steps.append({"tool": tc.function.name, "args": args, "status": status})
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": json.dumps(payload, ensure_ascii=False, default=str)})
    finally:
        if raw:
            raw.close()
    checked = verify((final or {}).get("findings"), mismatches, tools)
    return {"nct_id": nct_id, "model": model, "reasoning_effort": reasoning_effort, "steps": steps,
            "tool_calls_used": used, "flags": flags, "turns": turns,
            "prompt_tokens": prompt_tokens, "completion_tokens": sum(t["usage"].get("completion_tokens") or 0 for t in turns),
            "cost_usd": round(sum(t["cost_usd"] for t in turns), 6), "latency_s": round(time.time() - t0, 1),
            "mismatches": [asdict(m) for m in mismatches], "model_final": final, "findings": checked}


def agreement(verdict: str, auto_category: str) -> bool | None:
    """Does the agent agree with the auto-grade? None when the auto-grade is not settled."""
    if auto_category in ("caught_up", "partly_caught_up"):
        return verdict == "registry_lagging"
    if auto_category in ("never_changed", "changed_other_way"):
        return verdict == "real_discrepancy"
    return None
