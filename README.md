Trial Feasibility Copilot is an agentic study-planning tool for trial sponsors. It reads a draft protocol PDF (text and visit-schedule images), searches 56,000 past ClinicalTrials.gov trials with SQL tools, and uses plain arithmetic to show recruitment bottlenecks before sign-off.

# Trial Feasibility Copilot

**Study-planning tool for trial sponsors, not medical advice.** It looks at recruitment logistics and timelines using public registry records. It uses no patient data and gives no clinical, diagnostic or treatment advice.

> Before you sign off a protocol, see the design choices that sank similar trials, with the evidence.

Built for the Meta AI Developer Hackathon (Oct 27 – Nov 4, 2026), problem statement "Build for Your World": the author's own domain, about 20 years in pharma within a roughly 30-year career.

## Status (Day 1, Oct 27)
- `app/extract.py` reads a protocol PDF into a trial card with Muse Spark 1.3. The full text gives the design fields, and the visit-schedule page images give the visit fields. Every value carries page citations.
- Results on the 5 demo protocols: [docs/day1.md](docs/day1.md), with the Oct 27 fixes in [docs/day1-fixes.md](docs/day1-fixes.md).
- Coming next: the search loop over the Jan 2017 registry pools (≤6 tool calls, hard stop), code-computed risk maths, the sponsor memo with checked citations, the web UI, and the backtest.

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
- **Visit burden is expected to matter only modestly.** This was stated before any result. Eligibility (how many patients qualify), competition from similar trials, and the number of sites and their enrollment rate are expected to dominate. The memo will not present visit burden as a main driver unless the held-out backtest shows it is.
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
