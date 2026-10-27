# Backtest, tuning set (563 trials, 36 stopped for poor enrollment)

Run Tue Oct 27, 2026, 6:30-7:27 PM ET. Held-out set (873 trials) not touched: no extraction, no search, no outcome read.
Analysis plan fixed before results: `docs/backtest-tuning-analysis-plan.md` (sha256 `6a6c8631…f9f6`).
Locked rule: `docs/preregistration-addendum.md` (sha256 `efa4ad81…0dc4`, recorded in the cohort MANIFEST).
Full numbers: `backtest/tuning_summary.json` (aggregates only). Code: `backtest/run.py`, `backtest/analyze.py`.

## Run
- 563 of 563 processed: 550 text PDFs (text call + schedule-image call), 12 scans (pages 1-10 as images), 1 stub (no readable text; registry-only score).
- Extraction failures: 0 (excluding the stub). 8 calls timed out during a ~10-minute API stall (7:02-7:12 PM ET); each was retried once, as logged, and succeeded.
- Schedule pages: page finder 346, text-call fallback 177, none found 27. Visit counts missing for 125 trials (22%), imputed with the tuning median.
- Search: 0 failures, 0 capped, median 3 tool calls.
- Spend: $4.38 on muse-spark-1.3-contributor (~$0.0078 per trial). Wall time about 57 minutes.

## Results (tuning; descriptive, the held-out run is the test)
Base rate 36/563 = 6.4% (stricter label: the same 36).

| Feature | AUC (95% CI, sponsor bootstrap) |
|---|---|
| Registry baseline A (in-sample: all 563 were in its training data) | 0.68 (0.60-0.76) |
| Comparable-trial poor-enrollment rate | 0.55 (0.44-0.66) |
| Patients per site per month | 0.51 (0.42-0.61) |
| Required biomarker (missing = no) | 0.53 (0.45-0.60) |
| Clinic visits days 1-85 (primary definition, observed n=438) | 0.50 (0.40-0.61) |
| All contacts screening-day 85 (sensitivity, observed n=438) | 0.52 (0.42-0.62) |

- Feature choice (CV log loss): no protocol feature beat A alone. B = A recalibrated.
- B out-of-fold: AUC 0.67 (0.59-0.76); B − A −0.007 (−0.016 to 0.002). Log loss 0.229 vs 0.236 for raw A; mean predicted 6.4% vs observed 6.4% (raw A predicts 3.6%); slope 0.88. Top 10%: 6 of 56 stopped (11%).
- Near-start protocols (199 trials, 14 events): A 0.67 (0.48-0.83); same picture.
- Extraction vs Jan 2017 registry (agreement, original / amended): phase 97% / 96%, randomized 99% / 97%, open label 96% / 96%, arms 87% / 91%, enrollment within 10% 86% / 80%, sites within 20% 75% / 75%.

## What it means
On the tuning set none of the four protocol features separates trials that later stopped for poor enrollment from those that didn't, beyond chance. The locked rule therefore uses no protocol feature, so on the held-out set B's AUC equals A's by construction; only calibration can differ.
