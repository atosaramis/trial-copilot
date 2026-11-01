# Primary-outcome triage: method notes

**Question.** For a trial with an early protocol, did the registered primary outcome change after the trial started? If it did, do the trial's own posted documents (amendments, analysis plans) explain the change?

## Pipeline
1. **Cohort (code).** The cohort is 1,436 trials with a protocol posted on ClinicalTrials.gov that were running on Jan 5, 2017. Data come from the CTTI AACT flat files.
2. **Change detection (code).** The registered primary outcomes are compared across the AACT snapshots (Jan 5, 2017; Jan 11, 2018; Jan 1, 2020; Jan 2, 2023) and the results section, using normalised fuzzy text matching. 1,015 trials changed.
3. **Change type (Muse Spark 1.3, bulk tier, public data only).** Each change is rated as wording, timeframe, added, dropped, different measure or unclear, with a severity score. 234 trials had severity 3, meaning a different main measure. Cost: $0.31.
4. **Early protocol (code).** Only trials whose protocol is dated before the start date were kept: 73.
5. **Protocol read (Muse Spark 1.3).** The model reads the protocol pages most likely to define the primary outcome. It quotes them with page numbers and says whether the protocol matches the early record, the later record or neither.
   - Code keeps a quote only if it finds the quote word for word on the cited page: 69 of 73 passed.
   - 33 trials were flagged: the protocol matches the early record and not the later one.
   - Cost: $1.62.
6. **Full document read (Muse Wonder 1.0).** For each of the 33, the model gets every posted protocol, amendment and analysis plan, page-marked and in date order, plus the registry primaries per snapshot and the results primary. It returns a verdict, the original and later primary, the explaining document (if any), 2-5 page-cited quotes, the decision timing, the reason and what would change the reading. Cost: $7.43 for about 1.5M input tokens.
   - Code checks every quote against its cited page: 130 of 140 passed; the rest are not shown.
   - NCT02525861 (about 2.5M characters) was trimmed: Amendments 2-6 were sent as pages 1-2 plus pages on the primary endpoint, summary of changes or rationale (51 of 473 pages). Amendment 1, Amendment 7 and the analysis plan were sent whole. NCT02682381 (about 1.2M characters) fit and was sent whole.
   - One scanned analysis plan was transcribed with Muse Spark vision ($0.02); quotes from it can't be checked by code.
   - Verdicts: 8 explained, 5 probable, 17 requiring review, 3 timing can't be settled, 0 possible data-entry error.
7. **Shortlist (code).** Requiring review or timing unsettled, excluding 8 trials whose original primary was a safety or pharmacokinetic list: 13 trials. The 4 probable efficacy cases and the 8 set aside are listed below the shortlist, not cleared.
8. **Agreement.** An earlier, separate AI-assisted review had checked 12 of the 33. Wonder agreed on 11 of 12 for explained vs not, and 9 of 12 on requires review / probable / explained (Cohen's kappa 0.61). Two AI readings agreeing is not evidence of being right. A blind hand-labelling sheet for all 33 has been prepared for a human reviewer.

## Limits
- **Not a prevalence estimate.** The cohort is trials that posted protocols. The number the filters missed is unknown.
- **Dates are windows.** Registry changes are dated only by the snapshots they fall between. The record history tab on ClinicalTrials.gov has exact dates, but it has no official API, so it was not collected automatically.
- **The first flag is often wrong.** Reading the amendments and analysis plans explained 8 of the 33 flagged trials. That is why the output is a review queue.
- **AI-adjudicated, not expert-verified.** No clinical expert has reviewed the verdicts yet. Wonder calls "requiring review" broadly, including recounted or regrouped safety measures.
- **Not medical advice and not a regulatory finding.** A change can be legitimate. A difference between public documents is a prompt to look.

## Sharing rules
Protocol PDFs stay on ClinicalTrials.gov. The app shows short quotes and links to the cited page of the official PDF. `scripts/build_outcome_view.py` reads a scan folder kept outside the repo refuses to save a hand-picked quote that code can't find on its page, and drops any model quote that fails the same check.
