# Tuning-set analysis plan (details fixed before any tuning extraction)

Written Tue Oct 27, 2026, 6:30 PM ET, before the first tuning protocol is extracted. It fills in the
details that preregistration.md (with Amendment 1) leaves open. It changes nothing there. Held-out trials
are not extracted, scored or looked at.

## Data
- Tuning set only: the 563 trials with split = "tuning" in prep/cohort_1436.csv. Outcome columns are read
  for these 563 rows only, by the analysis script, after extraction is finished.
- Extraction: muse-spark-1.3-contributor, reasoning "minimal", fixed prompts (sha256 recorded). Text PDFs:
  one text call plus one schedule-image call. Scans of 10+ pages: one call on images of pages 1-10.
  Stubs (<10 pages, no text): no call, no protocol features. Texts over 2.8M characters are trimmed
  from the end (flagged).
- Search: the same agentic search as the app (at most 6 tool calls) on the contributor model, on the frozen
  Jan 5, 2017 pools, with the trial's own record excluded.

## Labels
- Primary: label_poor_enrollment. Secondary (stricter): tests/label-rule/strict_label.py applied to the
  primary label and the stop reason (tuning keeps 36 of 36, so the secondary results equal the primary).

## Registry baseline (A)
- lar36/data/baseline_split.pkl (the "split" model in baseline_locked.json), applied unchanged to the 13
  registry features from lar36/data/lar36_2017.pkl. Note: all 563 tuning trials were in A's training data,
  so A's tuning AUC is in-sample.

## Candidate protocol features (exactly these four, as pre-registered)
1. pace: planned N / (sites x enrollment months) from app/risk.py (protocol values, registry fallbacks as
   the app does). Used as log(pace), pace clipped to [0.001, 20].
2. biomarker: 1 if the card's required_biomarker is a non-empty value that is not a negation
   (none, not required, not applicable, n/a, no); else 0.
3. clinic visits days 1-85 (Amendment 1 primary definition): card clinic_visits_first_12_weeks, clipped to
   [0, 60]. Sensitivity definition (reported, never selectable): contacts_screening_to_week_12.
4. comparable rate: the poor-enrollment stop rate among the comparable set the search chose (2017 outcomes).
   No comparable set: the pool rate 2,359 / 56,509.
- Missing values (failed extraction, stub, field not stated): the tuning median of the transformed feature
  (biomarker: 0). Missingness is reported per feature.

## Model B and feature choice
- B = logistic regression, L2, C = 1.0, on standardised [logit(A probability), chosen features].
- Candidate sets: every subset of the four features with 0 to 3 members (15 sets; the empty set is A
  recalibrated). Criterion: mean out-of-fold log loss over 20 repeats of stratified 5-fold CV (seeds 0-19,
  the same folds for every set). The lowest wins; a set within 0.0005 of the lowest with fewer features wins.
- The chosen B is refit on all 563 trials; coefficients, scaler means/scales and imputation medians are frozen.

## Reported on the tuning set (descriptive; the confirmatory test is the held-out run)
- Base rates (primary and stricter label), extraction outcomes and failure rate, feature missingness.
- Per feature (both visit definitions included): univariate AUC (direction-free orientation not used:
  higher value = higher predicted risk) with a 95% CI from 2,000 bootstrap reps resampling lead sponsors.
- A: AUC (in-sample) with CI. B: out-of-fold AUC (one 5-fold CV, seed 0) with CI, and the paired B - A
  difference with CI. Log loss, mean predicted vs observed rate, calibration slope and intercept,
  10-bin calibration table, precision in the top 10%.
- Near-start subgroup (protocol date <= start + 31 days): the same, descriptive only.
- Frozen in preregistration-addendum.md: chosen features, coefficients, scaler, medians, transforms,
  prompt hashes, model id, code commit. Its sha256 goes into prep/MANIFEST.md.

## Go/no-go for the held-out run (stated now)
The held-out run is worth doing if extraction succeeds for at least 90% of readable protocols. The tuning
AUC is not a gate: the held-out run is the test, and a tie is reported as a tie.

## Additions (6:38 PM ET, during the extraction run, before any analysis or outcome has been read)
- Extraction-accuracy subgroup (pre-registration subgroup 3): agreement of card fields with the Jan 2017
  registry record (registry not treated as truth), on trials where both values exist:
  planned enrollment within 10%; planned sites within 20% or 2 sites; phase equal; randomized yes/no equal;
  open label vs blinded equal; number of arms equal. Split "original" (document type names original/initial
  or version 0, or document date <= start + 31 days) vs "amended" (all others). No outcome is used.
- The schedule-page fallback (text call's schedule_of_assessments_pages, used when the page finder finds no
  grid) was added after trial 1 of the 20-trial pilot; that trial's schedule call was re-run with it, so all
  563 trials use the same settings.
- Extraction failure = no card (API error, unreadable stub) or the text call returned unparseable JSON.
  "Visits missing" (no schedule found or not countable) is reported separately as feature missingness.
