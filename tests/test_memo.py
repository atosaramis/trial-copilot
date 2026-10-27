"""Memo: Wonder writes from the evidence pack; code checks every trial ID and number."""
import json
from types import SimpleNamespace

import pytest

from app.memo import REMOVED_ID, REMOVED_NUM, build_evidence, check_memo, cost_usd, render_markdown, write_memo

CARD = {"condition": "Multiple Myeloma", "phase": "Phase 2", "n_arms": 2, "planned_enrollment": 112,
        "planned_sites": 20, "clinic_visits_first_26_weeks": 24, "clinic_visits_first_12_weeks": 18,
        "soc_invasive_procedures_first_26_weeks": 3, "research_invasive_procedures_first_26_weeks": 0}
AUDIT = {"search": {"steps": [{"step": 1, "tool": "search_comparable_trials", "args": {"condition_terms": ["myeloma"]},
                               "rows": 395, "reason": "start broad"}]},
         "risk": {"comparable_trials": {"n": 112, "events": 11, "rate": 0.0982, "ci95": [0.0557, 0.1674],
                                        "outcome_counts": {"completed": 88}},
                  "all_trials_in_pool": {"n": 56509, "events": 2359, "rate": 0.04175, "ci95": [0.0401, 0.0434]},
                  "relative_to_pool": 2.35,
                  "site_pace": {"patients_per_site_per_month": 0.1, "planned_enrollment": 112, "sites": 20,
                                "sites_source": "protocol", "months": 56.0, "months_source": "registry",
                                "comparable_completed_median_pace": 0.3214, "comparable_completed_iqr": [0.13, 0.83],
                                "share_of_completed_comparables_at_least_this_fast": 0.857}}}


@pytest.fixture
def ev():
    e = build_evidence(CARD, AUDIT, pools_dir=None, nct_id="NCT99999999")
    e["allowed_nct_ids"] = ["NCT00366106", "NCT00124579"]
    return e


def _memo(evidence="11 of 112 comparables stopped for poor enrollment [F5], 9.8% vs 4.2% [F6].", trials=None):
    b = {"title": "Slow enrollment", "evidence": evidence, "what_to_check": "Confirm 20 sites.",
         "facts": ["F5"], "trials": trials or []}
    return {"headline": "Enrollment risk is 2.35 times the pool.", "bottlenecks": [b, dict(b), dict(b)],
            "evidence_limits": "Thin."}


def test_pack_has_no_audited_id_and_no_2020_outcomes(ev):
    assert "NCT99999999" not in ev["text"]
    assert "2020" not in ev["text"] and "outcome_2020" not in ev["text"]


def test_clean_memo_passes(ev):
    clean, rep = check_memo(_memo(trials=["NCT00366106"]), ev)
    assert rep["passed"], rep
    assert rep["numbers"]["checked"] > 5 and not rep["numbers"]["removed"]


def test_unknown_trial_id_is_removed(ev):
    clean, rep = check_memo(_memo("Like NCT01234567 and NCT00366106 [F5].", trials=["NCT07777777"]), ev)
    assert REMOVED_ID in clean["bottlenecks"][0]["evidence"] and "NCT01234567" not in json.dumps(clean)
    assert "NCT00366106" in clean["bottlenecks"][0]["evidence"]
    assert clean["bottlenecks"][0]["trials"] == [] and not rep["passed"]
    assert "NCT07777777" in rep["trial_ids"]["removed"]


def test_number_the_model_computed_is_removed(ev):
    # 112 - 11 = 101 and 9.8 / 4.2 = 2.33 are not in the pack (2.35 is)
    clean, rep = check_memo(_memo("101 comparables did not stop; a 2.33-fold rate [F5]."), ev)
    assert rep["numbers"]["removed"].count("101") == 3 and "2.33" in rep["numbers"]["removed"]
    assert REMOVED_NUM in clean["bottlenecks"][0]["evidence"]


def test_rounding_and_percent_forms_allowed(ev):
    clean, rep = check_memo(_memo("About 10% stopped (9.82%); pace 0.32 vs 0.1; 85.7% faster; 86% [F5]."), ev)
    assert not rep["numbers"]["removed"], rep["numbers"]


def test_unknown_fact_tag_and_framing_flagged(ev):
    clean, rep = check_memo(_memo("Stopped early [F99]. This is a treatment recommendation [F5]."), ev)
    assert "F99" in rep["fact_tags"]["unknown"] and "[F99]" not in clean["bottlenecks"][0]["evidence"]
    assert rep["framing"] == ["treatment recommendation"] and not rep["passed"]


def test_too_few_bottlenecks_flagged(ev):
    m = _memo()
    m["bottlenecks"] = m["bottlenecks"][:2]
    assert not check_memo(m, ev)[1]["passed"]


def test_markdown_shows_check(ev):
    clean, rep = check_memo(_memo(), ev)
    md = render_markdown(clean, rep)
    assert "Check:" in md and "trial ID citations verified" in md and "not medical advice" in md


class _FakeClient:
    def __init__(self, payload):
        self.payload, self.calls = payload, []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        msg = SimpleNamespace(content=json.dumps(self.payload))
        d = {"choices": [{"finish_reason": "stop"}], "usage": {"prompt_tokens": 1000, "completion_tokens": 500}}
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)], model_dump=lambda: d)


def test_write_memo_with_fake_client():
    fc = _FakeClient(_memo("Stopped in NCT05555555; 11 of 112 [F5]."))
    out = write_memo(CARD, AUDIT, nct_id="NCT99999999", client=fc)
    kw = fc.calls[0]
    assert kw["model"] == "muse-wonder-1.0" and kw["response_format"] == {"type": "json_object"}
    assert "NCT99999999" not in kw["messages"][1]["content"]
    assert out["check"]["trial_ids"]["removed"] == ["NCT05555555"] * 3
    assert out["cost_usd"] == cost_usd({"prompt_tokens": 1000, "completion_tokens": 500}) == 0.014
    assert out["latency_s"] >= 0


def test_more_than_five_bottlenecks_trimmed_to_five(ev):
    m = _memo()
    m["bottlenecks"] = [dict(m["bottlenecks"][0], title=f"B{i}") for i in range(6)]
    clean, rep = check_memo(m, ev)
    assert [b["title"] for b in clean["bottlenecks"]] == ["B0", "B1", "B2", "B3", "B4"]
    assert rep["trimmed"] == ["B5"] and "dropped by code" in render_markdown(clean, rep)


def test_number_outside_cited_facts_is_flagged():
    ev = build_evidence(CARD, AUDIT, pools_dir=None, nct_id="NCT99999999")
    f_enroll = next(f for f, v in ev["fact_numbers"].items() if 112.0 in v and 20.0 not in v)
    # 2,359 is in the pack (pool events) but not in the planned-enrollment fact this bottleneck cites
    clean, rep = check_memo(_memo(f"112 planned, 2,359 elsewhere [{f_enroll}]."), ev)
    assert "2,359" in rep["numbers"]["not_in_cited_facts"] and not rep["numbers"]["removed"]
    assert "flagged for review" in render_markdown(clean, rep)
