# Day 2 (Oct 27, evening): past-trial search and enrollment-risk numbers

This is a study-planning tool for trial sponsors. It is not medical advice. Every number below is about recruitment logistics, read from public registry records as they stood on **Jan 5, 2017**.

## What was built
- **`app/tools.py`**: three read-only DuckDB tools over the frozen Jan 5, 2017 registry pools.
  - `search_comparable_trials` searches 56,509 past trials. Filters: condition terms, phase, biomarker, intervention, sponsor type, size and start year.
  - `count_competing_trials` counts trials that were recruiting on Jan 5, 2017 (41,458 in the pool).
  - `get_trial` returns one Jan 2017 record.
  - Terms match at the start of a word, so "SCLC" does not pick up "NSCLC". No tool can return a column from a later snapshot.
  - The audited trial is excluded from its own comparables and competitors.
- **`app/agent.py`**: the search loop.
  - Muse Spark 1.3 calls the tools at most 6 times. Every call carries a one-line reason, and each step is logged for the UI trace: the tool, its arguments, the reason and the rows returned.
  - Muse accepts only `tool_choice: "auto"`, so the hard stop works like this: after 6 calls the model gets one "budget used" message, and code refuses any further call (logged as "not run: search capped").
  - Code checks the model's final pick and falls back to its own pick when the model's doesn't hold up.
  - The model sees the trial card's design fields, plus the countries from the Jan 2017 record. It never sees the NCT ID, so it can't recall how the real trial went.
- **`app/risk.py`**: the risk numbers, all computed by code ("computed, not guessed").
  - The poor-enrollment stop rate among comparables, with a Wilson 95% interval, compared against the whole pool.
  - The needed pace: patients per site per month = planned enrollment ÷ (sites × months). This is placed against the paces that completed comparables actually achieved: enrollment ÷ (sites × months from start to primary completion).
  - A 101-point pace curve, so the UI sliders (sites, months) can update instantly in the browser.
  - The count of competing trials and their sites.
  - Sites come from the protocol first, with the Jan 2017 registry count as fallback. Any mismatch is flagged.
- **`app/audit.py`**: search plus risk for one trial card.
- **`scripts/day2_search_eval.py`**: the evaluation runner. Its relevance check (one disease pattern per demo trial) was written before any run.

## Search effort: minimal vs low
The test covered 3 demo protocols (myeloma, EGFR lung, COPD) × 2 settings × 2 repeats on the contributor rate. Quality is the share of returned trials that match the disease (a size between 30 and 500 earns full marks).

| Setting | Quality | Cost per search (contributor) | Same search at standard rate | Time | Tool calls | Tool errors | Same cohort size on both repeats |
|---|---|---|---|---|---|---|---|
| minimal | 0.983 | $0.0022 | ~$0.029 | 9 s | 3.2 | 0 | 2 of 3 |
| low | 0.986 | $0.0020 | ~$0.028 | 17 s | 3.3 | 1 | 1 of 3 |

Quality per dollar is a tie: about 34 vs 36 quality points per standard-rate dollar. Minimal is chosen because it is twice as fast for the live trace, had no tool errors, and was steadier between repeats. Low spends about 4× the reasoning tokens (1,022 vs 247) for the same answer.

## Demo searches (standard rate, minimal)
All 5 searches ran on Oct 27 at the standard rate, costing $0.098 in total. The rates below are 2017 registry outcomes of past comparable trials only, against 4.2% for the whole pool (2,359 of 56,509).

| Demo trial | Comparable set the agent chose | Poor-enrollment stops (95% CI) | vs pool | Pace needed (pts/site/mo) | Completed comparables at least this fast | Competing trials (sites) |
|---|---|---|---|---|---|---|
| **Myeloma NCT02720510** | Phase 2 myeloma with bortezomib or lenalidomide (112) | **11 / 112 = 9.8% (5.6–16.7%)** | **2.35×** | 0.10 (20 sites, 56 mo†) | 86% | 98 in the US (1,523) |
| EGFR lung NCT01857271 | Phase 2 NSCLC with EGFR (137) | 10 / 137 = 7.3% (4.0–12.9%) | 1.75× | 0.31 (5 sites, 36 mo) | 46% | 108 in the US (1,896) |
| SCLC NCT02735980 | Phase 2 extensive-stage small cell (58) | 3 / 58 = 5.2% (1.8–14.1%) | 1.24× | 0.11 (57 sites‡, 19 mo†) | 57% | 35 in its countries (419) |
| COPD NCT02155660 | Phase 3 COPD (303) | 1 / 303 = 0.3% (0.1–1.8%) | 0.08× | 0.12 (380 sites, 47 mo†) | 99% | 42 (1,143) |
| Alzheimer's NCT02760602 | Phase 2–3 prodromal AD / MCI (44) | 0 / 44 = 0% (0–8.0%) | 0× | 0.18 (240 sites‡, 58 mo†) | 100% | 30 (2,014) |

† The protocol states no enrollment period, so code uses the registry's start-to-planned-primary-completion span. That span includes follow-up, so the pace shown is a floor (flagged on the card).
‡ The protocol gives no site count, so the Jan 2017 registry count is used.

**Myeloma, slider check.** The protocol says 20 sites, but the Jan 2017 registry lists 5. With 5 sites the needed pace is 0.40, and only 43% of completed comparables enrolled that fast. With 5 sites over 24 months it is 0.93, which 18% managed. The comparable stop rate is 2.35× the pool, and 98 other Phase 2 myeloma trials were recruiting in the US at the same time.

Each search took 2–5 tool calls and 3–8 s, and cost $0.013–0.030 at the standard rate.

## Two Day 1 values fixed
1. **"Highly recommended" is not mandatory.** The schedule reader now quotes each procedure's requirement wording, and code (`procedure_is_mandated`) treats recommended, highly recommended, strongly encouraged, optional, if clinically indicated and similar as not mandatory, whatever the model said.
   - EGFR NCT01857271: the mediastinoscopy is not mandatory in 3 of 3 runs (I, J, K), and standard-of-care procedures counted = 0 in all three.
2. **The screening window is always filled when the protocol shows it.** The prompt now gives an order: (1) timing of the first screening visit, (2) a stated screening period, (3) the longest required "within N days of study entry" footnote. When the model still leaves it blank, code reads it from the screening visit labels ("V1 (w-4)" gives 28, "Day -28 to -1" gives 28). A stated value is kept, and any mismatch with the labels is flagged.
   - COPD NCT02155660: 28 days in 3 of 3 runs.
   - Rule (3) gives EGFR 56 days (PFTs within 8 weeks), where Day 1 run H gave 28 (scans within 28 days).
   - Alzheimer's reads 56. The model reports it, and code flags that the visit labels give 28.

The trial card also gained `condition` and `interventions` (from the text) for the search.

**Still wobbly (not fixed tonight):** the myeloma MRD marrow sample in complete responders changed between runs. Run I read it as research-only and not mandatory; run J as research-only and mandatory; run K as standard of care and mandatory. The bone marrow procedures counted moved between 3 and 4.

## Tests
92 pass (`pytest -q`). They cover:
- the tools on a tiny synthetic pool: no later-snapshot columns, the audited trial excluded, word-start matching, bad arguments;
- Wilson values, pace, the slider curve, and the sites and months fallbacks;
- the search loop with a scripted fake model: the 6-call cap, the "budget used" message, tool errors returned to the model, code fallback, and that the NCT ID never reaches the model;
- the two fixes;
- repo hygiene: no PDFs, keys, cohort file, pools, protocol text or prep scripts.

## Not in the repo
The registry pools (`data/pools/`, git-ignored) stay out until the deploy decision. The tools read `TRIAL_COPILOT_POOLS_DIR`. The cohort file and its later outcomes are never read by the search code.
