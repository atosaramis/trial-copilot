"""The search loop with a scripted fake model (no API calls)."""
import json

from openai.types.chat import ChatCompletion

from app.agent import MAX_STEPS, card_brief, cost_usd, run_search
from app.audit import search_and_risk
from app.tools import RegistryTools


def _completion(tool_calls=None, content=None, n=0):
    msg = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = [{"id": f"call_{n}_{i}", "type": "function",
                              "function": {"name": name, "arguments": json.dumps(args)}}
                             for i, (name, args) in enumerate(tool_calls)]
    return ChatCompletion.model_validate({
        "id": f"x{n}", "object": "chat.completion", "created": 0, "model": "muse-spark-1.3",
        "choices": [{"index": 0, "finish_reason": "tool_calls" if tool_calls else "stop", "message": msg}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 100, "total_tokens": 1100}})


class FakeClient:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.chat = self
        self.completions = self

    def create(self, **kw):
        self.calls.append(kw)
        return self.script.pop(0)


SEARCH = ("search_comparable_trials", {"reason": "start broad", "condition_terms": ["myeloma"], "phase": ["Phase 2"]})
COMPETE = ("count_competing_trials", {"reason": "competition", "condition_terms": ["myeloma"]})


def test_normal_run_logs_every_step(pools):
    t = RegistryTools(pools, exclude_nct="NCT02720510", target_enrollment=112)
    fake = FakeClient([_completion([SEARCH], n=1), _completion([COMPETE], n=2),
                       _completion(content='{"comparable_search": "S1", "competing_search": "C1", "summary": "ok"}', n=3)])
    seen = []
    out = run_search({"condition": "multiple myeloma", "phase": "Phase 2"}, t, client=fake, on_step=seen.append)
    assert out["tool_calls_used"] == 2 and not out["capped"]
    assert [s["tool"] for s in out["steps"]] == ["search_comparable_trials", "count_competing_trials"]
    assert out["steps"][0]["reason"] == "start broad" and out["steps"][0]["rows"] == 40
    assert "reason" not in out["steps"][0]["args"]
    assert seen == out["steps"]
    assert out["comparable_search"] == "S1" and out["competing_search"] == "C1"
    assert out["cost_usd"] == round(3 * (1000 * 1.25e-6 + 100 * 4.25e-6), 6)
    assert all(c["reasoning_effort"] == "minimal" for c in fake.calls)


def test_hard_stop_after_six_calls(pools):
    t = RegistryTools(pools)
    script = [_completion([SEARCH], n=i) for i in range(MAX_STEPS)]
    script.append(_completion([SEARCH, SEARCH], n=99))   # the model still wants more
    script.append(_completion(content="not json", n=100))
    fake = FakeClient(script)
    out = run_search({"condition": "myeloma"}, t, client=fake)
    assert out["tool_calls_used"] == MAX_STEPS
    assert out["capped"] and "search capped" in out["flags"]
    assert sum(1 for s in out["steps"] if s["status"] == "not run: search capped") == 2
    assert all("tool_choice" not in c for c in fake.calls)  # Muse supports only "auto"
    nudges = [m for m in fake.calls[-1]["messages"] if m.get("role") == "user" and "budget used" in m["content"]]
    assert len(nudges) == 1
    # code picks the last usable comparable search and runs the competing count itself
    assert out["comparable_search"] == f"S{MAX_STEPS}"
    assert out["competing_search"] == "C1"
    assert any("counted by code" in f for f in out["flags"])


def test_tool_errors_go_back_to_the_model(pools):
    t = RegistryTools(pools)
    bad = ("search_comparable_trials", {"reason": "oops", "condition_terms": [], "phase": ["Phase 2"]})
    fake = FakeClient([_completion([bad], n=1), _completion([SEARCH], n=2),
                       _completion(content='{"comparable_search": "S9"}', n=3)])
    out = run_search({"condition": "myeloma"}, t, client=fake)
    assert out["steps"][0]["status"] == "tool error"
    tool_msgs = [m for m in fake.calls[1]["messages"] if m.get("role") == "tool"]
    assert "error" in json.loads(tool_msgs[0]["content"])
    assert out["comparable_search"] == "S1"  # S9 does not exist; code fell back
    assert any("not usable" in f for f in out["flags"])


def test_model_never_sees_the_nct_id(pools):
    card = {"condition": "multiple myeloma", "phase": "Phase 2", "planned_enrollment": 112,
            "visit_schedule": {"x": 1}}
    fake = FakeClient([_completion([SEARCH], n=1), _completion([COMPETE], n=2),
                       _completion(content='{"comparable_search": "S1", "competing_search": "C1"}', n=3)])
    res = search_and_risk(card, "NCT02720510", pools, client=fake)
    sent = json.dumps(fake.calls[0]["messages"])
    assert "NCT02720510" not in sent and "visit_schedule" not in sent
    assert "United States" in sent  # countries from the Jan 2017 record
    assert res["risk"]["comparable_trials"]["n"] == 40
    assert res["risk"]["site_pace"]["registry_sites_2017"] == 5
    assert "NCT02720510" not in res["retrieved_nct_ids"]


def test_card_brief_and_contributor_price():
    b = json.loads(card_brief({"condition": "COPD", "phase": None, "masking": "Double"}, "France"))
    assert b == {"condition": "COPD", "masking": "Double", "countries_in_registry_record_jan_2017": "France"}
    u = {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}
    assert cost_usd(u, "muse-spark-1.3-contributor") == 0.30
    assert cost_usd(u, "muse-spark-1.3") == 5.50
