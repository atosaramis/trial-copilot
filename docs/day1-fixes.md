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
4. Also: the whole schedule table is sent (up to 8 pages, was 3), with its text layer and the page after it, for footnotes. Bone marrow biopsy or aspirate required of every participant counts as a mandatory fresh biopsy. A protocol-required surgery needing admission counts as an inpatient stay. Biopsy and inpatient stay are "yes" if either the text or the schedule reading says yes.

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
