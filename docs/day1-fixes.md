# Day 1 fixes: visit counts, phone visits, age rule (Tue Oct 27, 2026, ET)

The overnight run (see `day1.md`) found three problems. All three are fixed, and the 5 demo protocols were re-run.

## What changed
1. **"Total visits" is gone.** On open-ended oncology schedules it depended on how repeating cycle columns were counted (the myeloma protocol gave 15 on one run and 27 on the next). Now the schedule call only *writes the schedule down* (screening visits, then periods with cycle length, number of cycles or "repeats until stop", and visit days), and code counts:
   - `clinic_visits_first_26_weeks`: study days 1 to 183 (day 1 = randomization or first dose; week n = day 7n + 1, so 183 is the nominal week-26 visit). This is the burden field.
   - `remote_visits_first_26_weeks`: phone, video and home contacts in the same window.
   - `clinic_visits_first_12_weeks` / `remote_visits_first_12_weeks`: days 1 to 85 (kept because the pre-registration names "visits in the first 12 weeks").
   - `screening_clinic_visits`: visits before day 1, counted separately.
   - `visits_open_ended`: treatment cycles repeat until progression or another stop event.
   - Counts are for one participant who stays on treatment through week 26. End-of-treatment, early-termination, unscheduled and "as needed" visits are not counted. Two contacts on the same day count once (clinic if either is at the clinic). A visit timed by a window ("surgery 4–6 weeks after the day-57 scan") is placed at the middle of the window and flagged.
2. **Phone visits are split out.** Each visit is marked clinic, phone, video or home. Burden uses clinic visits.
3. **Age rule.** The text call now quotes the age criterion, and code applies the registry convention: the lower limit is the number as written ("Age > 18", "≥ 18", "18 or older" all give 18), and the upper limit is the oldest allowed age ("< 75" gives 74, "≤ 75" gives 75). 22 wording cases are tested.
4. Also: the whole schedule table is sent (up to 8 pages, was 3), with its text layer and the page after it, for footnotes. Bone marrow biopsy or aspirate required of every participant counted as a mandatory fresh biopsy (**reversed in the second round below**). A protocol-required surgery needing admission counts as an inpatient stay. Inpatient stay is "yes" if either the text or the schedule reading says yes.

## Results (two final runs, D and E)
| Protocol | Clinic visits, 26 wk | Remote, 26 wk | Clinic, 12 wk | Screening | Open-ended | Registry agreement |
|---|---|---|---|---|---|---|
| NCT02720510 (myeloma) | 24 / 24 | 0 / 0 | 18 / 18 | 1 | yes | 9/10 |
| NCT01857271 (EGFR lung) | **7 / 6** | 0 / 0 | 5 / 5 | 1 | no | 7/7 |
| NCT02735980 (small-cell lung) | 27 / 27 | 0 / 0 | 13 / 13 | 1 | yes | 7/7 |
| NCT02155660 (COPD) | 5 / 5 | 3 / 3 | 3 / 3 | 3 | no | 8/10 |
| NCT02760602 (Alzheimer's) | 7 / 7 | 0 / 0 | 4 / 4 | 1 | no | 8/8 |

- **Registry agreement: 39/42** (was 38/42). The age fix turned NCT01857271 into a match. The 3 remaining differences are the protocol-vs-registry differences already noted in `day1.md` (planned sites on NCT02720510 and NCT02155660, countries on NCT02155660), not reading errors.
- **Run to run:** 113 of 115 compared values identical. Myeloma visit counts were the same on all 5 runs today (24 clinic in 26 weeks, 18 in 12 weeks), and they match a hand count from Table 7-1. The two differences: NCT01857271 clinic visits 7 vs 6 (after day 57 the schedule hangs on when surgery happens, and one run treated surgery as conditional), and the myeloma brain-metastases field ("Not applicable" vs blank).
- The COPD trial (20 numbered visits, 7 by phone) now shows 5 clinic and 3 phone contacts in the first 26 weeks, plus 3 screening visits.

## Spend
$1.85 at the standard rate (1,260,043 tokens in, 74,922 out): three full runs, one 2-protocol schedule probe, and two schedule-only runs.

## Second round (Oct 27, decisions by Rafal after a second-opinion review)
### What changed
1. **Screening stays separate** from the visit burden. New field `screening_window_days` gives the stated screening window length (e.g. "Day −28 to −1" → 28).
2. **Pre-registration amendment.** Amendment 1, dated 2026-10-27, was written before any unblinding.
   - "Visits in the first 12 weeks" now means clinic visits on nominal study days 1–85.
   - The original wording is a pre-specified sensitivity analysis: every contact, clinic or remote, from screening through day 85. Code reports it as `contacts_screening_to_week_12`.
   - Both get reported. No visit-count vs termination association has been examined.
   - The new sha256 is in `prep/MANIFEST.md`, next to the old one.
3. **Invasive procedures by purpose.** The schedule call lists every biopsy, bone marrow sample, lumbar puncture or endoscopy. For each it records:
   - the purpose: standard of care, or research only;
   - whether every participant must have it;
   - when it happens.

   Code counts the mandated occurrences on study days up to 183, screening included, giving `soc_invasive_procedures_first_26_weeks` and `research_invasive_procedures_first_26_weeks`. `mandatory_fresh_biopsy` now means a mandated research-only procedure, so **a myeloma bone marrow sample no longer counts**. Rules:
   - Fixed timepoints in a row that also has "as clinically indicated" extras are mandated.
   - An extra tube drawn at a marrow procedure done anyway is not a separate procedure.
4. **Surgery is a major procedure, not a clinic visit.** It stays on the timeline, so later visits can be timed from it, but it is not counted. It is reported as `major_procedure_required`, `major_procedure_day` and `major_procedure_inpatient_days` (when stated).
   - Pre-op and post-op assessment visits still count.
   - The rule is in both the text and schedule prompts, and code also recognises a surgery by its label.
   - A follow-up whose frequency changes ("every 3 months the first year, then every 6") uses the first frequency.
   - A "Day 0" inside the treatment schedule is read as Day 1. One run labelled the COPD week-0 randomisation visit "day 0", which had pushed it into screening.
5. **Limitations** were added to the README and build spec (§13):
   - registry-posted protocols skew toward industry and results-posted trials, and may under-represent early-terminated ones;
   - visit burden is expected to be a modest contributor; eligibility, competition and site count are expected to dominate.

### Results (two final runs, G and H, same prompts)
| Protocol | Clinic, 26 wk | Remote, 26 wk | Clinic, 12 wk | Screening visits / window | Sensitivity count (all contacts, screening–day 85) | Surgery | Mandated procedures, 26 wk (standard of care / research) | Research biopsy | Registry |
|---|---|---|---|---|---|---|---|---|---|
| NCT02720510 (myeloma) | 24 / 24 | 0 | 18 / 18 | 1 / 21 days | 19 / 19 | no | 3 / 0 (marrow: screening, C4D21, C6D1), both runs | **no**, both runs | 9/10 |
| NCT01857271 (EGFR lung) | **6 / 6** | 0 | 5 / 5 | 1 / 28 days | 6 / 6 | yes, day ~92, both runs | 0 / 0 vs **1** / 0 | no | 8/8 |
| NCT02735980 (small-cell lung) | 27 / 27 | 0 | 13 / 13 | 1 / 28 days | 14 / 14 | no | 0 / 0 (biopsies optional) | no | 7/7 |
| NCT02155660 (COPD) | 5 / 5 | 3 / 3 | 3 / 3 | 3 / **blank vs 28** | 8 / 8 | no | 0 / 0 | no | 8/10 |
| NCT02760602 (Alzheimer's) | 7 / 7 | 0 | 4 / 4 | 1 / 56 days | 5 / 5 | no | 0 / 0 (lumbar punctures optional) | no | 8/8 |

- **Run to run: 148 of 150** compared values identical (30 fields × 5 protocols).
  - The EGFR 6-vs-7 wobble is gone. Code now leaves the surgery out of the count, and both runs read it as a required major procedure around day 92.
  - The myeloma brain-metastases field is "Not applicable" on both runs; the text prompt now says so for blood cancers.
  - Two values still differ:
    - EGFR mediastinoscopy: one run called it mandatory. The protocol says "highly recommended", so the correct count is 0.
    - The COPD screening window: one run left it blank. The schedule shows visit 1 at week −4, i.e. 28 days.
- **Registry agreement: 40/43.** The new text reading also filled countries = 1 for NCT01857271 (US sites only), matching the registry. The 3 differences are the same protocol-vs-registry ones as before.
- Run G reused run F's text reading. Run H re-read the myeloma text (for the brain-metastases check) and reused run F's text for the other four. The text prompt changes (surgery, research biopsy and brain-metastases wording) are the same in F and H.
- The 12-week clinic counts are unchanged by this round on all 5 protocols.

### Spend
$0.93 at the standard rate (594,492 tokens in, 48,386 out): one full run, two schedule-only runs and one myeloma text re-read.
