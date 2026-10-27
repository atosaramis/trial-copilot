# Pre-registration addendum: locked scoring rule (tuning run done; held-out untouched)

Written Tue Oct 27, 2026, 7:35 PM ET. preregistration.md planned this addendum for Fri Oct 30; it is
written earlier, at Rafal's instruction, right after the tuning run. Still true when written: no
held-out protocol has been extracted, searched or scored, and no held-out outcome has been read.

## Chosen protocol features: none
The pre-registered choice (cross-validated log loss on the 563 tuning trials; 15 candidate sets of 0-3
of the four candidates; 20 repeats of stratified 5-fold CV) picked the empty set. Model B is therefore
the registry baseline A recalibrated on the tuning set, with no protocol feature:

    p_B = 1 / (1 + exp(-(0.797195 + 1.053194 * logit(p_A))))

- p_A: probability from the locked 13-field baseline (lar36/data/baseline_split.pkl, "split" model in
  baseline_locked.json), applied unchanged; logit(p) = log(p/(1-p)), p clipped to [1e-6, 1-1e-6].
- Fitted as LogisticRegression(C=1.0, L2, lbfgs) on standardised logit(p_A): mean -3.471740,
  scale 0.641224, coefficient 0.675334, intercept -2.859222.
- Runner-up sets (CV log loss; lower is better): none 0.22836; visits 0.22906; comparable rate 0.22988;
  biomarker 0.23038; pace 0.23050.

Consequence, stated before the held-out run: B is a monotone transform of A, so on the held-out set
AUC(B) = AUC(A) and the paired difference is 0 by construction. The held-out comparison can only
differ in calibration (log loss, mean predicted vs observed, slope and intercept, 10-bin plot) and in
nothing about ranking.

## Extraction settings frozen with it (used for the tuning run; any held-out run must use the same)
- Model muse-spark-1.3-contributor, reasoning effort "minimal"; one text call + one schedule-image call
  (pages from the page finder, else the pages the text call names); scans of 10+ pages: one call on
  pages 1-10; stubs: no call. Search: app search agent, at most 6 tool calls, frozen Jan 5, 2017 pools.
- Code commit: trial-copilot 4600f71.
- Prompt sha256:
  - trial_card_text.txt 9865c62a0e4aa15306c6c1a5a34d913377a3a906ba470dfe00b933584fed3fb3
  - visit_schedule_vision.txt d44676f6a78f2c2f65e01c498b9f8f1419f1874528c1ed48f524f9ec01361f8e
  - search_agent.txt 0de6839ec42884c5b8190e6f457b341aeaba32697bbbe3e8474f42b184cebbdf
- Analysis plan (written before any tuning result): backtest-tuning/analysis_plan.md, sha256
  6a6c8631aa7f498f7d0d1843d730ffc24436a01146b31ce0bc300ad63f34f9f6
- Tuning results file: backtest-tuning/summary.json, sha256 bb6add78a81913b31d4750c06fdd2d0ed3ee669d790cc1db5ca5b7eb76788b12
- Frozen model file: backtest-tuning/frozen_model.json, sha256 991bf9dd47a364d9ffdd2889e98eec7a6830bfb66910f2386bac2a457b1a6a46
