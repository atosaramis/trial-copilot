"""Mismatch investigation agent: tool loop, budget stop, spend cap and citation checks (fake client)."""
import json
from types import SimpleNamespace as NS

import pytest

from app.mismatch import agent as ag
from app.mismatch.autograde import Snapshot
from app.mismatch.finder import Evidence, Mismatch
from app.mismatch.ledger import BudgetExceeded, SpendLedger

PAGES = ["Title page of the protocol with enough words to read. " * 5,
         "Synopsis. The study will enrol 112 patients at approximately 20 sites in the United States and Europe. " * 2,
         "Statistics. Accrual of 2 patients per site per month is assumed. " * 3]
SNAPS = {"2017": Snapshot("2017", n_sites=5, enrollment=112, enrollment_type="Anticipated", phase="Phase 2"),
         "2020": Snapshot("2020", n_sites=5, enrollment=31, enrollment_type="Actual", phase="Phase 2"),
         "2023": Snapshot("2023", n_sites=5, enrollment=31, enrollment_type="Actual", phase="Phase 2")}
MM = [Mismatch("NCT1", "sites", 20.0, 5.0, "high", "protocol_higher", (), Evidence(2, "…20 sites…", "stated"))]
GOOD = {"findings": [{"field": "sites", "verdict": "real_discrepancy", "protocol_value": 20,
                      "explanation": "The protocol plans about 20 sites; the registry lists 5 and never changed.",
                      "protocol_citations": [{"page": 2, "quote": "The study will enrol 112 patients at approximately 20 sites"}],
                      "registry_citations": [{"snapshot": "2017", "field": "sites", "value": 5},
                                             {"snapshot": "2023", "field": "sites", "value": 5}]}]}


def resp(content=None, calls=(), pt=1000, ct=100):
    tcs = [NS(id=f"c{i}", function=NS(name=n, arguments=json.dumps(a))) for i, (n, a) in enumerate(calls)]
    msg = NS(content=content, tool_calls=tcs or None,
             model_dump=lambda exclude_none=True: {"role": "assistant", "content": content,
                                                   "tool_calls": [{"id": t.id, "type": "function",
                                                                   "function": {"name": t.function.name, "arguments": t.function.arguments}} for t in tcs]})
    d = {"choices": [{"finish_reason": "tool_calls" if tcs else "stop"}], "usage": {"prompt_tokens": pt, "completion_tokens": ct}}
    return NS(choices=[NS(message=msg)], model_dump=lambda: d)


class Fake:
    def __init__(self, replies):
        self.replies, self.sent = list(replies), []
        self.chat = NS(completions=NS(create=self.create))

    def create(self, **kw):
        assert "tool_choice" not in kw          # Muse accepts automatic tool choice only
        self.sent.append(kw)
        return self.replies.pop(0)


def run(replies, tmp_path, cap=5.0, **kw):
    fake = Fake(replies)
    led = SpendLedger(tmp_path / "ledger.jsonl", cap)
    out = ag.investigate("NCT1", MM, ag.TrialTools(PAGES, SNAPS), led, fake, "muse-spark-1.3", **kw)
    return out, fake, led


def test_tool_loop_verifies_quotes_and_registry_values(tmp_path):
    out, fake, led = run([resp(calls=[("read_pages", {"pages": [2]}), ("get_registry_history", {"field": "sites"})]),
                          resp(json.dumps(GOOD))], tmp_path)
    (f,) = out["findings"]
    assert f["verdict"] == "real_discrepancy" and len(f["protocol_citations"]) == 1 and len(f["registry_citations"]) == 2
    assert f["dropped"] == [] and out["tool_calls_used"] == 2
    assert led.spent() == out["cost_usd"] > 0
    tool_msgs = [m for m in fake.sent[1]["messages"] if m["role"] == "tool"]
    assert "approximately 20 sites" in tool_msgs[0]["content"] and '"2020": 5' in tool_msgs[1]["content"]


def test_invented_quote_and_wrong_registry_value_are_dropped(tmp_path):
    bad = json.loads(json.dumps(GOOD))
    bad["findings"][0]["protocol_citations"] = [{"page": 2, "quote": "the study will open forty sites across Asia"}]
    bad["findings"][0]["registry_citations"] = [{"snapshot": "2020", "field": "sites", "value": 20}]
    out, _, _ = run([resp(json.dumps(bad))], tmp_path)
    (f,) = out["findings"]
    assert f["verdict"] == "ambiguous" and f["protocol_citations"] == [] and len(f["dropped"]) == 2
    assert "no quote code could find" in f["checks"][0]


def test_quote_on_neighbouring_page_is_corrected_and_lagging_needs_a_later_value(tmp_path):
    g = json.loads(json.dumps(GOOD))
    g["findings"][0]["verdict"] = "registry_lagging"
    g["findings"][0]["protocol_citations"][0]["page"] = 3
    g["findings"][0]["registry_citations"] = [{"snapshot": "2017", "field": "sites", "value": 5}]
    out, _, _ = run([resp(json.dumps(g))], tmp_path)
    (f,) = out["findings"]
    assert f["protocol_citations"][0] == {"page": 2, "quote": g["findings"][0]["protocol_citations"][0]["quote"],
                                          "page_corrected_from": 3}
    assert f["verdict"] == "ambiguous" and "2020/2023" in f["checks"][0]


def test_budget_message_then_code_refuses_more_tools(tmp_path):
    many = [resp(calls=[("search_protocol", {"query": "sites"})]) for _ in range(3)]
    out, fake, _ = run(many + [resp(calls=[("read_pages", {"pages": [1]})]), resp(calls=[("read_pages", {"pages": [1]})])],
                       tmp_path, max_steps=3)
    assert out["tool_calls_used"] == 3
    assert any(s["status"] == "refused" for s in out["steps"])
    assert sum("Budget used" in str(m.get("content")) for m in fake.sent[-1]["messages"] if m["role"] == "user") == 1
    assert "model kept calling tools after the budget message" in out["flags"]
    assert out["findings"][0]["verdict"] == "ambiguous"


def test_hard_cap_refuses_the_call_before_sending(tmp_path):
    led = SpendLedger(tmp_path / "l.jsonl", 0.001)
    fake = Fake([resp(json.dumps(GOOD))])
    with pytest.raises(BudgetExceeded):
        ag.investigate("NCT1", MM, ag.TrialTools(PAGES, SNAPS), led, fake, "muse-spark-1.3")
    assert fake.sent == [] and led.spent() == 0


def test_ledger_persists_across_instances(tmp_path):
    p = tmp_path / "l.jsonl"
    a = SpendLedger(p, 1.0)
    h = a.reserve(0.3)
    a.record(h, 0.25, nct_id="X")
    b = SpendLedger(p, 1.0)
    assert b.spent() == 0.25
    with pytest.raises(BudgetExceeded):
        b.reserve(0.8)


def test_tools_handle_no_text_and_search():
    t = ag.TrialTools([], SNAPS)
    assert "error" in t.call("read_pages", {"pages": [1]})
    t = ag.TrialTools(PAGES, SNAPS)
    hits = t.call("search_protocol", {"query": "per site per month"})["hits"]
    assert hits[0]["page"] == 3
    assert t.call("get_registry_history", {"field": "enrollment"})["values"]["2020_type"] == "Actual"


def test_agreement_mapping():
    assert ag.agreement("registry_lagging", "caught_up") and ag.agreement("registry_lagging", "partly_caught_up")
    assert ag.agreement("real_discrepancy", "never_changed") and not ag.agreement("extraction_error", "never_changed")
    assert ag.agreement("real_discrepancy", "ambiguous") is None


def test_prompt_has_no_blame_words_except_the_ban():
    p = ag.PROMPT.read_text().lower()
    assert "do not use words like violation, non-compliance or fraud" in p
    assert p.count("non-compliance") == 1


def test_pages_sent_as_a_string_or_bad_args_do_not_crash(tmp_path):
    t = ag.TrialTools(PAGES, SNAPS)
    assert [p["page"] for p in t.call("read_pages", {"pages": "[2, 3]"})["pages"]] == [2, 3]
    assert [p["page"] for p in t.call("read_pages", {"pages": 1})["pages"]] == [1]
    out, fake, _ = run([resp(calls=[("search_protocol", {"query": None})]), resp(json.dumps(GOOD))], tmp_path)
    assert out["steps"][0]["status"] in ("ok", "tool error") and out["findings"][0]["verdict"] == "real_discrepancy"
