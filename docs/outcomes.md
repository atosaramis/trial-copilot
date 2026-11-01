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
6. **Document review (AI-assisted).** 12 of the 33 have so far been checked against every posted amendment and analysis plan. One scanned plan was read with Muse Spark vision ($0.02).
   - 3 still need review.
   - 3 are probable.
   - 6 are explained by the documents. Examples: a dated amendment, a protocol whose primary was pharmacokinetic all along, a pilot with no pre-defined primary, or a registry co-primary that the protocol never had.

## Limits
- **Not a prevalence estimate.** The cohort is trials that posted protocols. The number the filters missed is unknown.
- **Dates are windows.** Registry changes are dated only by the snapshots they fall between. The record history tab on ClinicalTrials.gov has exact dates, but it has no official API, so it was not collected automatically.
- **The model's first call is often wrong.** 6 of the first 12 flagged trials were explained by documents the protocol read had not seen. That is why the output is a review queue.
- **AI-checked, not expert-verified.** No clinical expert has reviewed the shortlist yet. 21 of the 33 have not yet been checked against their amendments and analysis plans.
- **Not medical advice and not a regulatory finding.** A change can be legitimate. A difference between public documents is a prompt to look.

## Sharing rules
Protocol PDFs stay on ClinicalTrials.gov. The app shows short quotes and links to the cited page of the official PDF. `scripts/build_outcome_view.py` reads a scan folder kept outside the repo and refuses to save any quote that code can't find on its page.
