# Day 1 results: reading the protocol PDF (Tue Oct 27, 2026, ET)

What ran: `app/extract.py` on the 5 demo protocols with `muse-spark-1.3`, `reasoning_effort: "minimal"`, JSON output, streamed, standard rate. One text call per protocol (full `pdftotext -layout` text, change-history blocks stripped, every page marked `=== PAGE n ===`) and one vision call per protocol (up to 3 visit-schedule pages rendered at 150 dpi). The card has 23 fields (the section 4 fields plus `enrollment_per_arm`). Raw API responses and page images are kept outside the repo.

The numbers below come from the second run (prompt v2, 00:34 ET). A first run (00:31 ET) found three prompt problems, listed under "Fixes made today".

## Per-protocol summary
| Protocol | Pages | Fields filled (cited) | Schedule pages sent (all found) | Found by | Latency text + vision (s) | Tokens in / out | Cost | Registry agreement (Jan 2017) |
|---|---|---|---|---|---|---|---|---|
| NCT02720510 (myeloma) | 104 | 20/23 (19) | 55, 56, 59 (55–59) | extra heading "Visit evaluation schedule" | 5.9 + 10.3 | 73,129 / 2,669 | $0.103 | 9/10 |
| NCT01857271 (EGFR lung) | 78 | 18/23 (18) | 22 (22) | extra heading "Schedule of Evaluations / Study Calendar" | 8.4 + 6.4 | 45,176 / 2,517 | $0.067 | 6/7 |
| NCT02735980 (small-cell lung) | 74 | 18/23 (18) | 11, 13, 15 (11, 13–15) | spec regex "Schedule of Activities" | 11.8 + 14.1 | 38,761 / 2,407 | $0.059 | 7/7 |
| NCT02155660 (COPD) | 133 | 19/23 (19) | 46, 49, 52 (46–47, 49–52) | extra heading "Study Plan" | 12.0 + 9.0 | 116,076 / 2,450 | $0.156 | 8/10 |
| NCT02760602 (Alzheimer's) | 73 | 16/23 (16) | 14, 15, 19 (14–19) | spec regex "Schedule of Activities" | 7.3 + 4.9 | 46,227 / 2,099 | $0.067 | 8/8 |
| **Total** | | | | | **mean 18.0 s per protocol** | **319,369 / 12,142** | **$0.451** | **38/42** |

"Fields filled" counts non-null values; the rest are null because the protocol does not state them (the prompt says never guess). "Cited" means the value has at least one valid page citation. Every citation points to a real page, and every vision citation points to one of the images sent. Registry agreement counts only fields where both the card and the registry have a value. The registry fields come from the Jan 5, 2017 snapshot: phase, planned enrollment, arms, allocation, masking level, minimum and maximum age, sponsor class (industry or not), sites and countries.

## Visit fields (read from the schedule page images)
| Protocol | Total visits | Visits in first 12 weeks | Open-ended cycles | Mandatory fresh biopsy | Inpatient stay | Text-only reading (total / 12 wk) |
|---|---|---|---|---|---|---|
| NCT02720510 | 27 | 18 | yes | yes (vision and text agree) | no (from text; images gave null) | null / null |
| NCT01857271 | 15 | 6 | no | no | yes (surgery stay; vision and text agree) | null / 5 |
| NCT02735980 | 8 | 13 | yes | no | no | null / null |
| NCT02155660 | 13 | 6 | no | no (from text) | no (from text) | 20 / 5 |
| NCT02760602 | 29 | 5 | no | no | no | 29 / 5 |

Vision filled the visit counts on all 5 protocols; text alone gave a total on only 2 and a 12-week count on 3. Vision gave null for biopsy and inpatient stay on 2 protocols, so code took the text reading and flagged it.

## Problems found
1. **The spec's schedule regex misses 3 of 5 protocols.** The headings were "Visit evaluation schedule", "Schedule of Evaluations / Study Calendar" and "Study Plan" (on the COPD protocol the only spec-regex hit was a figure called "Study Flow Chart"). The finder now also uses a few extra headings and scores pages by check-mark density, skipping contents pages. All 5 schedules were found.
2. **Schedules run past 3 pages on 4 of 5 protocols** (5–6 pages each). The finder sends the first and last page of the table, so the final visit number is visible. The vision prompt now counts visits hidden by a numbering gap (V9, then V20). That fixed NCT02760602 (19 visits in run 1, 29 in run 2, matching the text reading).
3. **Open-ended oncology schedules.** When cycles repeat until progression, "total visits" depends on how repeating columns are counted. NCT02735980 gives 8 total against 13 in the first 12 weeks, and code flags it. On NCT02720510 the model counted cycles 2–5 once in run 1 (15) and separately in run 2 (27). This field needs a firmer definition before the risk maths uses it, for example "visits in the first 26 weeks".
4. **Phone visits.** NCT02155660 has 20 numbered visits, 7 of them phone calls. Vision excludes phone calls (13). The text reading counted all 20.
5. **Registry differences that are not extraction errors:**
   - NCT02720510 plans "approximately 20 centers"; the Jan 2017 registry lists 5 sites.
   - NCT02155660 plans about 380 sites in 24 countries; the registry lists 362 sites in 26 countries.
   - NCT01857271 says "Age > 18". Read strictly, that is 19, against 18 in the registry. The "exclusive limit" rule added in v2 caused this, so it's worth revisiting.
6. **Often not stated:** planned sites and countries (3 of 5 null), enrollment period (4 of 5 null), longest washout (2 of 5 null). These will fall back to the Jan 2017 registry counts in the risk maths, as section 2 of the spec allows.
7. **Change history.** NCT02735980 includes its amendment summary (Appendix 7, pages 63–74, which repeats the schedule tables) and a "Rationale for Amendment" subsection (pages 19–21). Both are stripped. That also stops the duplicated schedule being picked. No other demo protocol had a change-history block, and the redaction junk word was removed from NCT02155660. Some PDFs print a version and date in every page header. That text still reaches the model, but no version, date or amendment field is ever extracted or kept.
8. Prompt caching didn't trigger (0 cached tokens), as on Oct 26.

## Fixes made today (run 1 → run 2)
- Sponsor type: NCT01857271 was "Industry" because a company supplies the study drug. The prompt now says the sponsor is the organisation that runs the trial. It's now "Academic/Other", matching the registry.
- Exclusive age limits ("< 75 years" → 74). This fixed NCT02720510.
- "All sites in one named country" → 1 country.
- Numbering-gap rule for visit counts (problem 2).

## Spend
Day 1 Meta API spend: run 1 $0.450 (318,684 in / 12,114 out), run 2 $0.451 (319,369 in / 12,142 out). **Total $0.90.** Reasoning tokens were 17,327 of the 24,256 output tokens.
