# Held-out results: the locked rule scored once on 873 trials

Written Tue Oct 27, 2026, about 8:15 PM ET. Held-out outcomes were read once, at 7:56 PM ET, by
`trial-copilot/backtest/heldout.py` (commit e2b8a61, committed before unsealing). The script first
checked that `preregistration-addendum.md` still has sha256
`efa4ad819bfb97721ff3d6e8e2cbe61444d4df4ebf3125eca7a8fd966eb40dc4` (as recorded in prep/MANIFEST.md)
and that the frozen model file matches the hash in the addendum. Nothing was refitted, re-chosen or
re-run after the outcomes were read. Cost: $0 (registry data only, no model call, no extraction).

## What was scored
- 873 held-out trials, 53 stopped for poor enrollment by Jan 1, 2020 (6.07%); 50 under the stricter label.
- A = the locked 13-field registry baseline, applied unchanged. None of the 873 held-out trials was in
  its training data (all 873 sit in the Oct 13 study's test split).
- B = A recalibrated on the 563 tuning trials (the pre-registered choice picked no protocol feature).
- Inputs: each trial's Jan 5, 2017 registry record only. No protocol was read for the held-out set.

## Pre-registered results (primary label, 873 trials, 53 events)
| | A (registry baseline) | B (locked rule) |
|---|---|---|
| AUC (95% CI, 2,000 sponsor-cluster bootstrap reps) | 0.662 (0.585 to 0.733) | 0.662 (0.585 to 0.733) |
| B − A AUC | | 0.000 (0.000 to 0.000), a tie by construction |
| Mean predicted vs observed | 3.5% vs 6.1% | 6.3% vs 6.1% |
| Calibration slope | 0.94 | 0.90 |
| Calibration intercept (in the large) | 0.58 | −0.05 |
| Log loss | 0.2276 | 0.2196 |
| Brier | 0.0567 | 0.0559 |
| Top 10% flagged (87 trials): stopped | 12 = 13.8% | 12 = 13.8% |

- **B vs A is a tie.** B is a monotone transform of A, so it ranks trials identically; this was
  stated in the addendum before unsealing. Reading the protocol added nothing that the pre-registered
  test could detect: the tuning-set selection chose no protocol feature (36 events: only large gains
  were detectable there).
- **What the recalibration did:** A under-predicted (3.5% predicted vs 6.1% observed). B's average
  matches the observed rate (6.3% vs 6.1%) and its log loss is lower. Slope 0.90 means B's spread is
  close to right, a little too wide.
- **Ranking is modest.** An AUC of 0.66 means a randomly chosen stopped trial scores above a randomly
  chosen non-stopped trial about two times in three. The top 10% had 13.8% stopped, about 2.3 times
  the base rate; 41 of 53 stops (77%) were outside the top 10%.

B's 10-bin calibration (tenths of held-out trials by B; mean predicted / observed / stops):
1.4%/1.1%/1, 2.4%/4.5%/4, 3.4%/6.8%/6, 4.3%/2.3%/2, 5.2%/0.0%/0, 6.3%/4.6%/4, 7.5%/8.0%/7,
8.7%/9.2%/8, 10.4%/10.3%/9, 14.0%/13.8%/12. With 87-88 trials per bin, single bins are noisy.

## Subgroups and sensitivity (reported, not used to choose anything)
- **Stricter label (50 events):** AUC 0.680 (0.598 to 0.754); B mean predicted 6.3% vs observed 5.7%,
  slope 1.01. B − A = 0 by construction.
- **Protocols dated near trial start (312 trials, 19 events):** AUC 0.619 (0.449 to 0.773); B mean
  6.1% vs observed 6.1%, slope 0.72. Too few events to test; descriptive only.
- **Extraction accuracy on the held-out set:** not run. The locked rule uses no protocol feature, so no
  held-out protocol was extracted, as the addendum required. Extraction agreement with the Jan 2017
  registry is available for the 563 tuning trials (docs/backtest-tuning.md).

## Caveats
- 53 events: the AUC interval is wide (0.59 to 0.73).
- Held-out trials can share lead sponsors with trials in A's training data; the sponsor-cluster
  bootstrap widens the interval for clustering but does not remove that overlap.
- The 5 demo trials are in the held-out set and were scored like every other trial.

## Exploratory, decided after unsealing (not part of the pre-registered result)
- The app shows each trial's B score next to how held-out trials with similar scores turned out,
  using fifths of the held-out set by B score (stops/trials: 5/176, 8/175, 4/174, 15/174, 21/174) with
  Wilson 95% intervals. This is a display choice made after reading outcomes; it does not change the
  score of any trial. Fifths were used instead of tenths because single tenths are noisy.

Machine-readable results: `backtest-heldout/heldout_summary.json`.
