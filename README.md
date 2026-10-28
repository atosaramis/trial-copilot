Trial Feasibility Copilot is an agentic study-planning tool for trial sponsors. It reads a protocol PDF (text and visit-schedule images), searches 56,509 past ClinicalTrials.gov trials with SQL tools, and, for trials with a Jan 5, 2017 ClinicalTrials.gov registry record, shows a registry-only risk score for a poor-enrollment stop (tested once on 873 held-out trials; a new protocol without a registry record gets no score), next to code-computed context for the reviewer to judge.

# Trial Feasibility Copilot

**Study-planning tool for trial sponsors, not medical advice.** It looks at recruitment logistics and timelines using public registry records. It uses no patient data and gives no clinical, diagnostic or treatment advice.

> Before you sign off a protocol, compare its plan with how similar past trials recruited and, when a Jan 2017 registry record exists, see a modestly predictive registry-only risk score, with the evidence.

Built for the Meta AI Developer Hackathon (Oct 27 – Nov 4, 2026), problem statement "Build for Your World": the author's own domain, about 20 years in pharma within a roughly 30-year career.

## Status (Day 4, Oct 27)
- **Backtest done (pre-registered).** Held-out result for the locked rule, which was made the app's headline number after this result: AUC 0.66 (95% CI 0.59 to 0.73) on 873 trials with 53 poor-enrollment stops; mean predicted 6.3% vs 6.1% observed; the top 10% of scores had 13.8% stopped (12 of 87), while 41 of the 53 stops (77%) fell outside the top 10%. It ranks trials modestly, nothing more. See [docs/backtest-heldout.md](docs/backtest-heldout.md).
- **Reading the protocol added no detectable gain.** On the 563 tuning trials (36 stops) the pre-registered selection chose no protocol feature, so the score is the registry-only baseline recalibrated, and on the held-out set it ties the baseline by construction. With 36 stops only large gains were detectable. See [docs/backtest-tuning.md](docs/backtest-tuning.md).
- **Headline number:** the calibrated registry-based risk (`app/registry_risk.py`: 13 fields of the Jan 5, 2017 registry record, no model call), shown with the held-out base rate, how held-out trials with similar scores turned out, and the held-out AUC.
- `app/extract.py` reads a protocol PDF into a trial card with Muse Spark 1.3. The full text gives the design fields, and the visit-schedule page images give the visit fields. Every value carries page citations. Results on the 5 demo protocols: [docs/day1.md](docs/day1.md), [docs/day1-fixes.md](docs/day1-fixes.md); agreement with the registry on 563 protocols is on the validation tab.
- Past-trial search: Muse Spark 1.3 calls three DuckDB tools over the Jan 5, 2017 registry pools (at most 6 calls, hard stop, every step logged). Code then computes the comparable poor-enrollment stop rate with a Wilson interval, needed vs achieved site pace (slider-ready), and competing trials. In the backtest the stop rate and pace showed no detectable link with outcome and competing counts were not tested, so the app shows them as context for reviewer judgement, not as risk scores. See [docs/day2.md](docs/day2.md).
- Sponsor memo: Muse Wonder writes the memo from a numbered evidence pack. It does no arithmetic. The headline states the registry-based risk, the held-out base rate with its counts and the held-out AUC with its interval; code checks that, rejects verdict words, and flags wording that calls a context item the biggest risk or a predictor. The 3-5 points that follow are things to check, not ranked risks. Code checks every trial ID and number against the pack and prints the result on the memo. See [docs/day3.md](docs/day3.md), [docs/day4.md](docs/day4.md).
- Web app (local): pick or upload a protocol, trial card with page badges and schedule images, live search trace, the registry-based risk, context numbers with sliders recomputed in the browser, memo with its check line, a sealed "what really happened" reveal for the 5 demos (all in the held-out set), and a validation tab with the tuning and held-out results. Saved demos replay with no API call; live mode is opt-in with a rate limit and a daily cap.

## Run the app
```bash
pip install -r requirements.txt
export TRIAL_COPILOT_POOLS=path/to/pools          # Jan 2017 pools (not in the repo)
uvicorn app.main:app --port 8765                  # http://localhost:8765
```
The 5 demos replay saved results (`demo_cache/`) without an API key. Set `TRIAL_COPILOT_LIVE=1` and `META_API_KEY` for live runs (per-visitor limit, $3/day cap).

## Run the extractor
```bash
sudo apt-get install poppler-utils          # pdftotext, pdftoppm
pip install -r requirements.txt
export META_API_KEY=...                      # from the environment only; never commit it
python -m app.extract path/to/protocol.pdf --out card.json --runs-dir /tmp/trial-copilot-runs
python -m app.extract path/to/protocol.pdf --dry-run   # no API call: schedule pages and sizes only
pytest -q
```
Page images and raw API responses go to `--runs-dir` (default `cache/runs/`, which git ignores).

## How the trial card is read
1. `pdftotext -layout` extracts the full text, one block per PDF page. The PDF itself is never sent, because the API reads only its first 100 pages.
2. Cleanup: Unicode normalisation, the redaction junk word `5HGDFWHG` removed, and "summary of changes", "amendment history", "revision history" and protocol-amendment appendix blocks stripped. Page numbers stay true.
3. Visit-schedule pages are found from their headings (`schedule of assessments/activities/events`, `time and events`, `study flow chart`, plus a few common variants) and check-mark density, skipping contents pages. The whole table (up to 8 pages) is rendered with `pdftoppm -png -r 150`.
4. `muse-spark-1.3` (`reasoning_effort: "minimal"`, JSON output, streamed) reads the text into the design fields. A second call reads the schedule page images (plus their text layer and the next page, for footnotes) and writes the schedule down as periods, cycles and visit days, each marked clinic, phone, video or home, plus the screening window length and every invasive procedure with its purpose (standard of care or research only) and timing. A protocol-required surgery is written down as a major procedure, not a visit. The model does not count.
5. Code (`app/visits.py`) lays the visits out on a study-day line and counts clinic and remote visits in the first 26 and 12 weeks from day 1, with screening counted separately. It also counts the mandated invasive procedures in the first 26 weeks by purpose, and flags a required surgery with its study day and any stated inpatient days. A bone marrow sample taken as routine myeloma care is not a research biopsy. Pre-op and post-op visits count, but the surgery itself does not. Code also turns the quoted age criterion into minimum and maximum age with the registry convention (`app/ages.py`: "Age > 18" gives 18, "< 75" gives 74), merges the two readings, checks every page citation, sums per-arm enrollment when the protocol gives no total, and flags anything odd. Field definitions: `docs/day1-fixes.md`.

Protocol version, dates and amendment details are never extracted or scored, because they can leak how a trial went.

## Limitations
- **Which trials have a posted protocol.** The backtest can only use trials that posted a protocol PDF on ClinicalTrials.gov. These skew toward industry-sponsored trials and trials with results posted from 2017 on. Trials that stopped early, especially small academic ones, post less often and may be under-represented. Results describe this kind of trial, not all trials.
- **The risk number ranks trials only modestly.** Held-out AUC 0.66 (0.59 to 0.73) from 53 events. Most trials that stopped (41 of 53) were not in the top 10% of scores. Use it to prioritise review, not to decide.
- **It is registry-only.** The score uses 13 fields of the Jan 2017 registry record. A new protocol with no registry record gets no score. In the backtest, protocol features and the comparable-trial stop rate gave no detectable improvement; competing-trial counts were not tested.
- **No detectable gain is not proof of no effect.** With 36 tuning-set stops, only large gains from protocol features could be detected. Visit burden, a required biomarker, the needed pace and the comparable stop rate each showed no detectable link with outcome alone (AUCs 0.50 to 0.55, intervals spanning 0.5).
- **Calibrated to one era.** The score was recalibrated on trials recruiting in Jan 2017 and checked on outcomes by Jan 2020. It may drift for other periods, regions or trial types.
- **Similar-score context is descriptive.** The "same fifth of scores" line uses fifths of the held-out set chosen after the outcomes were read (labelled exploratory in docs/backtest-heldout.md). It does not change any score.
- **Counts are nominal.** Visit and procedure counts use nominal study days for one participant who stays on treatment, with windows ignored. Timings that the protocol gives only as a window are placed mid-window and flagged.
- **Purpose is a judgement.** Whether a procedure is standard of care or research only is read from the protocol's wording. It carries a page citation so the user can check and correct it.

## Scope & pre-hackathon disclosure
**Built during the hackathon (Oct 27 – Nov 4, 2026):** all app code, prompts, tool wrappers, risk maths, the memo and citation check, the backtest runner and the statistics.

**Prepared before the event, from public data, and disclosed here:**
- The 1,436-trial cohort list and its tuning/held-out split.
- The Jan 2017 comparable and competing trial pools.
- The downloaded protocol PDFs. They aren't redistributed.
- The biomarker prevalence table with citations.
- The choice of 5 demo trials, made before any model read them.
- A 5-protocol API feasibility pilot (Oct 13–23).

**Prior research:** an Oct 13 study of 7 non-Meta models on 15,634 registry records is motivation only. It isn't part of this project.

## Data sources
Registry data: U.S. National Library of Medicine, ClinicalTrials.gov, via the CTTI AACT database (snapshots Jan 5, 2017; Jan 1, 2020; Jan 2, 2023).

Protocols may be copyrighted by their sponsors, so this repo links to them on ClinicalTrials.gov and never copies them. No PDFs or extracted protocol text are stored here. See [data/DATA_PROVENANCE.md](data/DATA_PROVENANCE.md).

## Licence
MIT (code only). See [LICENSE](LICENSE).
