# Data provenance

All inputs are public records. No patient data is used anywhere.

## Registry snapshots (CTTI AACT flat files of ClinicalTrials.gov)
| Snapshot | Used for | sha256 of the AACT zip |
|---|---|---|
| Jan 5, 2017 | Trial features, comparable-trial and competing-trial pools (the "prediction date": nothing later is used as an input) | `7f43a4f4d4af8bb514623ebf0896332b18058c0340956daab3354f9610eaa1ea` |
| Jan 1, 2020 | Outcomes only: shown in the "reveal" and used for backtest scoring, never as a tool input | `84e4f5413f750745ac99b45679234a45aeafc9b249075cf33f75dfdf2bc5b6bb` |
| Jan 2, 2023 | The list of posted protocol documents (which trials have a protocol dated before Jan 5, 2017) | `12ab38219856a415e4dc5d424cf9355b6ed0f853290697be5d524ea019b9d146` |

Attribution: Registry data: U.S. National Library of Medicine, ClinicalTrials.gov, via the CTTI AACT database (snapshots Jan 5, 2017; Jan 1, 2020; Jan 2, 2023).

## Cohort (prepared before the hackathon, disclosed)
- 1,436 phase 2–4 interventional trials that were recruiting on Jan 5, 2017. Each has a known outcome by Jan 1, 2020 and at least one posted protocol dated before Jan 5, 2017. There are 89 registry-reported poor-enrollment stops.
- Fixed split: 563 tuning trials (36 events) and 873 held-out trials (53 events). The 5 demo trials come from the held-out set and were chosen by a written rule before any model read them.
- 68% of the posted protocols are amended versions dated after the trial started (still before Jan 5, 2017). Version and amendment details are never extracted or scored, and change-history sections are stripped before a model reads the text.
- The cohort files and pools will be added under `data/` with their hashes. The SQL used to build them is described in words here and is not shipped as code.

## Protocol PDFs
- Each trial's earliest protocol dated before Jan 5, 2017 is fetched from ClinicalTrials.gov (`cdn.clinicaltrials.gov/large-docs/...`) when the app runs.
- PDFs, extracted text and rendered page images are **not** stored in this repo, because protocols may be copyrighted by their sponsors. The `.gitignore` blocks `*.pdf`, `protocols/`, `cache/` and page images.

## Demo protocols
| NCT ID | Disease area | Protocol (linked, not copied) |
|---|---|---|
| NCT02720510 | Multiple myeloma | https://cdn.clinicaltrials.gov/large-docs/10/NCT02720510/Prot_000.pdf |
| NCT01857271 | EGFR-mutant lung cancer | https://cdn.clinicaltrials.gov/large-docs/71/NCT01857271/Prot_SAP_000.pdf |
| NCT02735980 | Small-cell lung cancer | https://cdn.clinicaltrials.gov/large-docs/80/NCT02735980/Prot_000.pdf |
| NCT02155660 | COPD | https://cdn.clinicaltrials.gov/large-docs/60/NCT02155660/Prot_000.pdf |
| NCT02760602 | Alzheimer's disease | https://cdn.clinicaltrials.gov/large-docs/02/NCT02760602/Prot_000.pdf |
