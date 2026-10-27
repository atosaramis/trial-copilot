# Day 3 (Oct 27): the checked sponsor memo, and a stable marrow count

## What was built

**The memo** (`app/memo.py`, prompt `app/prompts/memo_wonder.txt`). Once per audit, after the search and the risk maths:

1. **Code builds an evidence pack.** Numbered facts (F1, F2, ...) in plain words: the trial card fields with protocol page numbers, every search step with the agent's stated reason, and every risk number code computed (comparable poor-enrollment stop rate and its 95% interval, pool rate, ratio to pool, pace needed, comparables' median pace and middle half, share at least that fast, sites needed to match the median, the registry-sites what-if, competing trials and sites, caveats). Then three short trial lists rebuilt from the saved search arguments: comparables that had stopped for poor enrollment (with their 2017 stop reason), completed comparables closest in size, and the largest competing trials. All of it is the Jan 5, 2017 registry snapshot. The audited trial's own NCT ID is never in the pack (asserted in code), and no 2020 field is read.
2. **Muse Wonder writes** (`muse-wonder-1.0`, standard rate, reasoning medium, JSON reply). The rules are: no arithmetic; every number must already be in the pack; cite only NCT IDs from the pack; tag each claim with its facts; 3 to 5 bottlenecks, most important first, each with one planning check; and say where the evidence is thin. Visit burden is a modest factor unless nothing stronger is in the pack.
3. **Code checks the memo before anyone sees it** (`check_memo`):
   - **Trial IDs.** Every NCT ID, in the text or in a bottleneck's trial list, must be in the pack. Anything else is replaced with "[unverified citation removed]".
   - **Numbers.** Every number outside an NCT ID or fact tag must match a pack number. The only allowance is rounding to the decimals written, or the fraction-to-percent form. Anything else is replaced with "[unverified number removed]".
   - **Numbers outside the cited facts.** A number that is in the pack but not in the facts or trials that bottleneck cites is kept but flagged for review. This catches a number taken from the wrong place.
   - **Fact tags.** Unknown fact tags are dropped and reported.
   - **Framing.** Banned framing words are flagged.
   - **Length.** More than 5 bottlenecks: code keeps the first 5 and says so.
4. **The memo shows the result** as one line, e.g. "Check: 12 of 12 trial ID citations verified; 31 of 31 numbers found in the inputs. All passed."

`app/audit.py` gains `audit_with_memo()` (search, then risk, then one memo). The run script `scripts/day3_memos.py` writes the 5 demo memos. With `--reuse` it re-checks saved replies at no cost, and it refuses to call the model if a saved reply is missing.

`app/framing.py` now holds the banned framing word list, which is used by both the memo check and the repo test. The test skips only that one file.

## Results on the 5 demos (standard rate)

Inputs: the Day 2 searches (`day2-runs/demo-search2`) and the cards re-merged with today's code (`day3-runs/replay-J`). Outputs are outside the repo in `day3-runs/memos/`.

| Demo | Bottlenecks | Trial IDs cited / verified / removed | Numbers checked / verified / removed | Wonder latency | Cost |
|---|---|---|---|---|---|
| Myeloma (NCT02720510) | 5 | 12 / 12 / 0 | 31 / 31 / 0 | 6.7 s | $0.040 |
| EGFR NSCLC (NCT01857271) | 5 | 10 / 10 / 0 | 41 / 41 / 0 (1 flagged: "36" in a check line that did not cite the enrollment-period fact) | 7.7 s | $0.041 |
| SCLC (NCT02735980) | 4 | 4 / 4 / 0 | 29 / 29 / 0 | 11.5 s | $0.048 |
| Alzheimer's (NCT02760602) | 5 | 6 / 6 / 0 | 30 / 30 / 0 | 8.9 s | $0.041 |
| COPD (NCT02155660) | 6, trimmed to 5 by code | 8 / 8 / 0 | 27 / 27 / 0 | 8.9 s | $0.041 |

Wonder latency is 6.7 to 11.5 s per memo (median 8.9 s). Each call is 2,000 to 2,800 tokens in and 1,400 to 1,900 out, with 550 to 1,220 of the output being reasoning. No ID or number had to be removed, and no framing word was flagged. A second, unplanned run on three demos (`day3-runs/memos-repeat/`, see spend) also passed with nothing removed: 11/11, 7/7 and 16/16 IDs.

The check is proven to bite by tests rather than by these runs. The tests cover an invented NCT ID, a model-computed difference and ratio, an unknown fact tag, a framing word, a number from the wrong fact, and too few or too many bottlenecks.

One gap was found and closed during the runs. The COPD memo wrote "26 countries" by counting the registry's country list itself. That number only passed because 26 also appears elsewhere (26 weeks). Code now states the country count in the pack, and the new cited-facts check flags any number taken from an unrelated fact.

### Myeloma memo (excerpt)

> Recruitment looks feasible at 20 sites, but US competition, site uncertainty, and narrow eligibility need checks before sign-off.
>
> **1. Heavy US competition for patients.** On Jan 5, 2017, 98 competing Phase 2 multiple myeloma trials were recruiting in the United States at 1,523 sites in total [F12, F20]. Large competing programmes included NCT02465060, NCT02654132, and NCT02654990 [F20].
>
> **2. Higher poor-enrollment stops in comparables.** Among 112 comparable past trials, 11 had stopped for poor enrollment by Jan 2017, which was 9.8% [F13]. That rate was 2.35 times the pool rate of 4.2% [F14, F15]. ...
>
> **3. Site count changes pace needed.** The protocol says 20 sites, but the Jan 2017 registry record lists 5 sites [F4, F21]. With 20 sites the pace needed is 0.10 participants per site per month, and 85.7% of completed comparables were at least as fast [F16, F17]. With 5 sites the pace needed is 0.40, and 42.8% of completed comparables were at least that fast [F19].
>
> Check: 12 of 12 trial ID citations verified; 31 of 31 numbers found in the inputs. All passed.

## The myeloma marrow wobble, fixed

**Cause.** The schedule has two bone-marrow rows at screening: the local plasma cell count and the MRD (ClonoSEQ) sample for complete responders. Across runs I, J and K, the model read the MRD row three ways: research and not required; research and required; standard of care and required. Because its screening mark falls on the same day as the plasma cell count marrow, the count moved between 3 and 4 standard-of-care procedures.

**Fix (the same pattern as the mandatory wording fix).**
- **Model quotes, code decides.** The model now quotes the row's own words (`purpose_wording`, `requirement_wording`), and code makes both calls (`app/visits.py`).
- **Purpose.** Research cues (MRD, ClonoSEQ, correlative, exploratory, biomarker, PK/PD, translational, research, biobank, sequencing) make it research-only.
- **Required or not.** Required wording ("X in schedule", "required", "in all patients ...") makes it required unless conditional wording is present ("if", "when", "suspected", "at progression", "to confirm", "either"). Explicit "not required" or "optional" wording makes it not required.
- **Same-day samples.** Same-kind invasive procedures on the same day count once (one marrow draw). That day counts as standard of care if any row on it is, and the merge is noted on the card.
- **Traceable.** The card keeps the model's original reading next to code's decision.

**Verified, 6 readings, all identical** (3 standard of care, 0 research-only, no mandatory research biopsy; PCC marrow standard of care and required; MRD research-only, required, merged with the screening marrow):

| Run | Model's MRD reading (purpose / required) | Code's decision | Count (SoC / research) |
|---|---|---|---|
| I (saved reply, re-merged) | research / no | research / yes | 3 / 0 |
| J (saved reply, re-merged) | research / yes | research / yes | 3 / 0 |
| K (saved reply, re-merged) | standard of care / yes | research / yes | 3 / 0 |
| L (fresh) | research / yes | research / yes | 3 / 0 |
| M (fresh) | research / no | research / yes | 3 / 0 |
| N (fresh) | research / no | research / yes | 3 / 0 |

The model still disagrees with itself in the fresh runs, but the card no longer does. The other 4 demos are unchanged by the new rules: the EGFR mediastinoscopy is not required, SCLC has none required, the Alzheimer's lumbar punctures are not required, and COPD has none.

## Tests

107 passing, including the hygiene and banned-words tests. New today: 3 marrow tests in `tests/test_visits.py` (the three saved readings give one outcome; research cues and conditional wording; a lone research marrow still counts), 11 memo tests in `tests/test_memo.py` (with a fake Wonder client), and 1 test pinning the shared banned-word list.

## Spend (Meta API, Oct 27, ET)

| Item | Cost |
|---|---|
| Wonder probe | $0.0014 |
| Fresh myeloma schedule runs L, M, N (Spark 1.3; text step reused) | $0.0905 |
| First myeloma memo (a save error lost its latency, so it was re-run) | $0.0456 |
| 5 demo memos (final) | $0.2106 |
| Unplanned repeat of 3 memos (a `--reuse` run pointed at an empty folder; stopped, and the script now refuses this) | $0.1443 |
| One memo call cut off by that stop (may or may not be billed) | up to ~$0.05 est. |
| **Day 3 total** | **$0.4925 measured (≤ ~$0.54 with the estimate)** |
