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
                                        "outcome_counts": {"completed": 88}, "completed_with_pace": 79},
                  "all_trials_in_pool": {"n": 56509, "events": 2359, "rate": 0.04175, "ci95": [0.0401, 0.0434]},
                  "relative_to_pool": 2.35,
                  "site_pace": {"patients_per_site_per_month": 0.1, "planned_enrollment": 112, "sites": 20,
                                "sites_source": "protocol", "months": 56.0, "months_source": "registry",
                                "comparable_completed_median_pace": 0.3214, "comparable_completed_iqr": [0.13, 0.83],
                                "share_of_completed_comparables_at_least_this_fast": 0.857}},
         "registry_risk": {"risk": 0.0929, "same_fifth_heldout": {"range": [0.0682, 0.0939], "n": 174, "events": 15,
                                                                  "rate": 0.0862, "ci95": [0.0529, 0.1374]},
                           "base_rate_heldout": {"events": 53, "n": 873, "rate": 0.0607},
                           "heldout_auc": {"auc": 0.6619, "ci95": [0.5853, 0.7334]}, "times_base_rate": 1.5}}
HEADLINE = ("Registry-based risk of a poor-enrollment stop by Jan 2020: 9.3%, against a 6.1% held-out base rate "
            "(53 of 873 trials); the score ranks trials only modestly (held-out AUC 0.66, 95% CI 0.59 to 0.73) [F1, F2].")


@pytest.fixture
def ev():
    e = build_evidence(CARD, AUDIT, pools_dir=None, nct_id="NCT99999999")
    e["allowed_nct_ids"] = ["NCT00366106", "NCT00124579"]
    return e


def _memo(evidence="11 of 112 comparables stopped for poor enrollment [F11], 9.8% vs 4.2% [F12].", trials=None):
    b = {"title": "Slow enrollment", "evidence": evidence, "what_to_check": "Confirm 20 sites.",
         "facts": ["F11", "F6"], "trials": trials or []}
    return {"headline": HEADLINE, "bottlenecks": [b, dict(b), dict(b)],
            "evidence_limits": "Thin."}


def test_pack_has_no_audited_id_and_no_2020_outcomes(ev):
    assert "NCT99999999" not in ev["text"]
    assert "outcome_2020" not in ev["text"] and "status_2020" not in ev["text"]
    # the registry-based risk comes first, and every past-trial number after it is marked as context
    assert ev["text"].split("\n")[2].startswith("F1: Registry-based risk") and "9.3%" in ev["text"]
    assert all(line.split(": ", 1)[1].startswith("Context for reviewer judgement")
               for line in ev["text"].splitlines() if "Comparable past trials chosen" in line or "Enrollment pace needed" in line)


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


@pytest.mark.parametrize("headline", [
    "Recruitment looks feasible at 20 sites, but 11 of 112 comparables stopped.",
    "The trial is not feasible: 11 of 112 comparables stopped.",
    "Enrollment looks fine; 11 of 112 comparables stopped.",
    "11 of 112 comparables stopped, but the plan is on track.",
])
def test_headline_verdicts_flagged(ev, headline):
    m = _memo()
    m["headline"] = headline
    clean, rep = check_memo(m, ev)
    assert rep["headline"]["verdict_words"] and not rep["passed"]
    assert "headline gives a verdict" in render_markdown(clean, rep)


def test_headline_must_state_the_registry_risk_and_base_rate(ev):
    m = _memo()
    m["headline"] = "Comparable trials stopped for poor enrollment at 9.8%, above the 4.2% pool rate."
    clean, rep = check_memo(m, ev)
    assert rep["headline"]["problems"] == ["headline does not state the registry-based risk, base rate and held-out AUC "
                                           "with its interval (9.3%, 6.1%, 53, 873, 0.66, 0.59, 0.73)"]
    m["headline"] = "Registry-based risk 9.3% [F1]."
    assert not check_memo(m, ev)[1]["passed"]
    m["headline"] = "Registry-based risk 9.3%, against a 6.1% base rate [F1, F2]."  # no AUC or interval
    assert not check_memo(m, ev)[1]["passed"]
    m["headline"] = HEADLINE
    assert check_memo(m, ev)[1]["passed"]


@pytest.mark.parametrize("text", [
    "The comparable stop rate is the biggest risk [F11].",
    "Pace is the main risk here [F14].",
    "A comparable rate of 9.8% predicts a stop [F11].",
    "The 2.35 times pool rate drives the risk [F13].",
])
def test_context_ranked_as_risk_or_predictor_is_flagged(ev, text):
    m = _memo(evidence=text)
    clean, rep = check_memo(m, ev)
    assert rep["claims"] and not rep["passed"]
    assert "risk-ranking or prediction wording flagged" in render_markdown(clean, rep)


def test_negated_prediction_wording_is_allowed(ev):
    m = _memo(evidence="This rate was not shown to predict outcome in the backtest [F3, F11].")
    assert check_memo(m, ev)[1]["claims"] == []


def test_no_registry_record_means_no_required_number():
    a = {k: v for k, v in AUDIT.items() if k != "registry_risk"}
    e = build_evidence(CARD, a)
    assert e["headline_numbers"] == [] and "Registry-based risk" not in e["text"]


def test_prompt_asks_for_registry_risk_headline_and_context_framing():
    from app.memo import PROMPT
    t = PROMPT.read_text()
    assert "headline states the registry-based risk" in t and "base rate" in t and "feasible" in t
    assert "Never call any of them the biggest, main, key or top risk" in t
    assert "biggest risk, which is bottleneck 1" not in t


def test_points_heading_says_what_was_and_was_not_tested(ev):
    from app.memo import POINTS_HEADING
    clean, rep = check_memo(_memo(), ev)
    md = render_markdown(clean, rep)
    assert f"### {POINTS_HEADING}" in md
    assert "no detectable link" in POINTS_HEADING and "competing trials were not tested" in POINTS_HEADING


def test_pack_gives_pace_denominator_and_no_rate_multipliers(ev):
    assert "Completed comparables with enrollment, site and date data (79 trials)" in ev["text"]
    assert "times the pool" not in ev["text"] and "times that" not in ev["text"]
    assert "Exploratory check chosen after the held-out outcomes were read" in ev["text"]
