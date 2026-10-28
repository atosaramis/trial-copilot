# Mismatch checker: protocol vs registry

New this week (Oct 27). Code: `app/mismatch/finder.py`, `app/mismatch/autograde.py`, batch runner
`scripts/mismatch_scan.py`, tests `tests/test_mismatch_finder.py` and `tests/test_mismatch_autograde.py`.
No model calls anywhere in this step. It costs $0 to run.

## The problem

A trial's protocol and its public registry entry describe the same study. They often disagree on
basic facts like how many sites, how many participants, the phase, or whether it is randomized. Usually nobody
notices. Anyone who benchmarks feasibility from the registry inherits those gaps.
The checker finds the gaps, shows the protocol page and quote for each one, and then uses later
registry versions to show what happened to each gap. It does not judge who was right or why.

## Step 1: finder (deterministic)

Inputs:
- the facts already extracted from the protocol (the trial card from the Day 1 to 3 pipeline);
- the Jan 5, 2017 registry record;
- the protocol text, one page per form feed.

| Field | Mismatch when | Severity |
|---|---|---|
| Sites | differs by more than max(2, 20% of the registry value) | high if one is at least 2x the other, else medium |
| Planned enrollment | differs by more than 10% | high at 2x or more, medium at 1.5x or more, else low |
| Countries | count differs | medium if off by more than 2 or 2x, else low |
| Phase | normalized phase sets differ | low if they overlap (Phase 2 vs Phase 2/3), else high |
| Randomized | randomized vs not | high |
| Arms | count differs | low (medium if off by 2 or more). This is mostly a counting convention, for example whether an extension cohort counts as an arm |

The finder looks for the sentence in the protocol that states the card's value. It handles digits,
number words ("thirty"), labelled fields ("Number of sites: 25", "N = 200", "Sample size of 50")
and ranges. It returns the page and a short quote. A sentence that states the number beats a range
end, and a range end beats a planning assumption.

Known traps, each flagged on the mismatch:

| Trap | What the code does |
|---|---|
| Range ("20-25 sites") | If any value in the range agrees with the registry, the gap is cleared and not reported (4 cases). Otherwise it is flagged as `range` |
| Statistical planning assumption ("statistical planning assume 40 enrollment sites") | Flagged `planning_assumption`, severity set to low |
| Placeholder registry entry (1 or 2 sites listed against a plan of 10 or more) | Flagged `registry_placeholder`, severity set to low. This trap is about the registry, not our reading |
| The registry's exact number also appears in the protocol | Flagged `registry_value_in_protocol`: both numbers are in the document, so the card may have picked the other one |
| Evaluable vs enrolled ("100 evaluable patients") | Flagged `evaluable_count` |
| Card value not found in the text | Flagged `quote_not_found`. This could be a misreading, or a value the model derived (for example by adding up the arms) |
| Scanned or garbled text layer | No quote and no trap. The quote has to come from the page images (the agent step below) |

Traps that cast doubt on our reading (range, planning assumption, quote not found, registry value
in protocol, evaluable count) cap severity at medium.

Primary endpoint timing is not compared yet. The trial card does not extract it, and the
registry tables we hold for 2017, 2020 and 2023 don't include outcome measures. It is a candidate
for the agent step.

## Step 2: auto-grade against later registry versions

For each mismatch, the code reads the same design field from the Jan 2020 and Jan 2023 AACT
snapshots. It reads only sites, countries, enrollment, phase, allocation and arms. Trial status and stop
reasons are never loaded here (a test checks this). The loader reproduces the 2017 record exactly
for all 563 tuning trials (sites, countries, enrollment, arms, phase).

| Category | Meaning |
|---|---|
| `caught_up` | The registry later reached the protocol value, so it was lagging (rules v2 also counted passing it) |
| `registry_exceeded_protocol` | Rules v3 only: the registry later moved past the protocol value and beyond tolerance (e.g. 5 → 50 sites against a plan of 20). The documents still disagree |
| `partly_caught_up` | The registry moved toward the protocol value but stayed short |
| `never_changed` | The registry kept its 2017 value (within the same tolerance) |
| `changed_other_way` | The registry changed, but not toward the protocol value |
| `ambiguous` | Can't be settled from the record (see below) |

A mismatch is ambiguous when:
- our reading is doubtful (one of the reading traps above), and the registry never later matched the protocol. If it did later match, that confirms our reading, so the mismatch counts as `caught_up`;
- for enrollment, only the planned (anticipated) number can show a correction. If the trial finished before the next snapshot, only the actual count remains. That can't show whether the plan was ever updated. The grade then records whether the actual count landed closer to the protocol or to the registry;
- there is no later record.

These categories describe what the public record did. They do not mean anyone was at fault, and they are not a compliance finding.

## Results on the 562 tuning trials with a card (rules v2, first scan)

These are tuning trials only. No held-out trial was read. They use the 2020 and 2023 snapshots for design fields only.

- Fields compared: sites 333, enrollment 537, countries 243, phase 379, randomized 407, arms 557.
- **270 mismatches in 206 trials.** 4 more were cleared by the range rule.
- Severity: high 45, medium 112, low 113.

| Field | caught_up | partly | never_changed | changed_other_way | ambiguous | Total |
|---|---|---|---|---|---|---|
| Sites | 27 | 10 | 32 | 2 | 11 | 82 |
| Enrollment | 2 | 1 | 4 | 0 | 87 | 94 |
| Countries | 2 | 0 | 3 | 2 | 7 | 14 |
| Phase | 0 | 0 | 9 | 3 | 0 | 12 |
| Randomized | 1 | 0 | 8 | 0 | 0 | 9 |
| Arms | 15 | 2 | 40 | 2 | 0 | 59 |
| **All** | **47** | **13** | **96** | **9** | **105** | **270** |

**Settled by the record: 165 of 270 (61%). Ambiguous: 105.** Of the ambiguous ones:
- 77 are enrollment gaps where the trial finished before the next snapshot;
- 28 are gaps where our reading is doubtful.

Without the arms field (mostly a counting convention), there are 211 mismatches in 182 trials. 106 of those are settled.

What this says, in plain words:
- Site gaps are often the registry lagging: 37 of 82 later caught up fully or partly. But 32 never changed.
- Enrollment gaps almost never get fixed while the trial runs. The registry's planned number was corrected in only 2 cases.
- Phase and randomization conflicts are rare (21 in total), but they almost never get corrected: 20 of 21 were never changed to match (17 kept the 2017 value, 3 changed another way). They are the cleanest flags for a sponsor to review.

## Optional expert labelling

There is a sheet of 31 hard or ambiguous trials (38 rows) for Rafal. It is kept outside the repo,
and only the tuning set is in it.

## Muse investigation agent: original plan (now built, see below)

For each mismatch, a Muse agent would:
- open the protocol pages around the quote, or the page images for scanned and garbled PDFs;
- search the rest of the protocol for competing numbers;
- read the three registry versions;
- write a short finding with page citations.

Code would then check the finding (the quote must exist on the cited page, and the numbers must match the record).

### Cost estimate (from logged usage)

What the estimate is based on (measured this week):
- Tuning backtest (562 trials, muse-spark-1.3-contributor, ledger total $4.38):
  - Extraction read the whole protocol: median 41.7k input / 2.8k output tokens.
  - The agentic search took a median 3 steps, at 17.0k input / 0.7k output.
- Demo runs on standard muse-spark-1.3 (minimal reasoning):
  - Search agent: $0.013 to $0.030 per trial.
  - Full extraction: $0.07 to $0.18 per trial.

Assumed per trial for the mismatch agent:
- Typical: about 35k input / 1.5k output. That's 4 turns of a growing context: the prompt and tools, then about 3 pages and 3 registry records per mismatch, with 1.3 mismatches per flagged trial.
- Low: 18k / 0.8k (like the search agent).
- High: 90k / 4k (page images for scans, several mismatches).

Prices: contributor $0.10/M input and $0.20/M output. Standard Spark $1.25/M input and $4.25/M output. Prompt caching is ignored, which is conservative.

| Run | Model | Trials | Per trial (low / typical / high) | Total (low / typical / high) |
|---|---|---|---|---|
| 5 demos, interactive | Spark 1.3 minimal (standard) | 5 | $0.026 / $0.050 / $0.13 | $0.13 / $0.25 / $0.65 |
| About 100 candidate trials | Spark 1.3 contributor | 100 | $0.002 / $0.004 / $0.010 | $0.20 / $0.38 / $0.98 |
| All flagged tuning trials | Spark 1.3 contributor | 206 | same | $0.41 / $0.78 / $2.0 |
| All flagged trials, full cohort (extrapolated) | Spark 1.3 contributor | about 530 | same | $1.1 / $2.0 / $5.2 |

Notes:
- The full-cohort row needs cards for the 873 held-out trials first. That extraction costs about $6.80 more (measured $0.0078 per trial) and would read held-out protocols.
- Allow about $2 to $3 for prompt development: about 50 Spark minimal runs on 10 tuning trials.
- Allow 1.5x for retries.
- A realistic all-in for demos, the 100 candidates and development is under $5.

## Investigation agent (Muse)

`app/mismatch/agent.py` gives Muse each mismatch the finder flagged and three local tools:
`read_pages`, `search_protocol` and `get_registry_history` (the 2017, 2020 and 2023 registry
values). It returns one verdict per mismatch:

- **real_discrepancy**: the protocol and the registry really disagree.
- **registry_lagging**: the registry later moved to the protocol's value.
- **extraction_error**: our reading of the protocol was wrong, for example an evaluable count, a
  maximum, or a number from a previous study.
- **ambiguous**: the evidence doesn't settle it.

Each verdict comes with a two-sentence plain-words explanation, a page and quote, and the
registry values it relies on.

**Code checks every claim.** A quote must appear on the cited page or the page next to it, and
a registry value must equal the snapshot value. Unsupported citations are dropped. A verdict is
downgraded to ambiguous when it has no verified quote, or when it says registry_lagging without
a verified 2020/2023 value. The prompt bans blame words such as violation, non-compliance or
fraud.

**Limits on spend.**

- An append-only ledger (`app/mismatch/ledger.py`) reserves each call's worst-case cost before
  sending it. It refuses any call that would cross the cap.
- Each trial gets 6 tool calls and 120k prompt tokens. After that the model gets a "budget used"
  message, and further tool calls are refused.
- Muse accepts only automatic tool choice, so the loop never forces a tool.

Run it with `python -m scripts.mismatch_agent_run`. Outputs go outside the repo.

### Results (2026-10-27)

| Run | Model | Trials | Mismatches | Cost |
|---|---|---|---|---|
| Dev + 5 demos | muse-spark-1.3, minimal | 5 (2 with mismatches) | 2 | $0.022 |
| Tuning candidates | muse-spark-1.3-contributor, minimal | 100 | 151 | $0.100 |
| Total (ledger) | | | | **$0.123** |

**Verdicts on the 151 tuning mismatches:**

- real_discrepancy: 67
- registry_lagging: 38
- extraction_error: 37
- ambiguous: 9

All 211 quotes were found word for word on the cited page; none had to be dropped.

**Agreement with the auto-grade.** 87 mismatches have a settled grade. The agent agrees on 60 of
them (69%). Without arms it agrees on 49 of 62 (79%). By field:

- sites: 30/36
- phase: 10/12
- randomized: 6/9
- arms: 11/25

**Where they disagree:**

- 17 times the auto-grade says "never changed" and the agent says our extraction was wrong.
  Examples: "up to 5 centers" read as exactly 5; 90 evaluable vs 300 consented; arm counts from
  multi-part designs. The auto-grade can't see extraction errors, so these are leads for the
  finder, not agent mistakes.
- 4 times the registry overshot the protocol (for example 5 → 50 sites against a plan of 20).
  The auto-grade counts that as caught up; the agent calls it a real discrepancy.

The 31 labelling-sheet trials were all included (53 mismatches), so hand labels can score the
agent later.

**Demos.**

- NCT02720510: page 9, "Patients will be enrolled at approximately 20 centers in the United
  States." The registry listed 5 sites in 2017, 2020 and 2023. Verdict: real discrepancy.
- NCT02155660: page 2, "…in 24 countries…". The registry listed 26 countries throughout.
  Verdict: real discrepancy, low severity.

The other three demos had no mismatches.

**Failure seen and fixed.** The contributor model once sent `pages` as the string
"[28, 29, 30]", which crashed the batch. Tools now accept that form, and any tool error goes
back to the model as a message. The interrupted trial was rerun once.

## Rule versions: v2 → v3 (2026-10-27)

Both the finder and the auto-grade take `rules="v2"` or `rules="v3"`; the default is v3. The
scripts take `--rules`. Re-running v2 reproduces the first scan exactly: the same 270 rows and the
same cleared list, compared order-insensitively. A test pins every v3 change against its v2
answer.

### What v3 changes

The changes come from the agent's 37 extraction-error verdicts on the 100 candidates.

| Pattern the agent found | v3 rule | Why not just clear it |
|---|---|---|
| "a minimum of three centres", "Sites 20 or more", "at least 60 patients" | `lower_bound`: cleared when the registry meets the minimum | Meeting a stated minimum is agreement |
| "up to 5 centers", "a maximum of 127 patients" | `upper_bound`: a doubtful reading, not cleared | In a first cut that cleared these, "up to 65 sites" against 9 registered was hidden even though the registry later grew to 25, a lagging registry |
| Registry equals another count in the protocol (screened, randomized, completed, a pilot or stage) | `count_definition`: each count gets a role from its nearest keyword. If the card took a completed/evaluable count and the registry equals the enrolled count, it is cleared. Otherwise it is flagged as doubtful and set to low | A loose first cut hid real cases: the registry corrected 60 → 90 (NCT02445859), and a 43 vs 188 gap with no funnel wording (NCT02053350) |
| Crossover sequences, Part 2 / Step 2, extensions, run-ins, observational groups, several sub-studies | `multi_part_design` on arms: doubtful and low | Arm counting in these designs is a convention, not a reading we can settle |
| "Phase III/IV" read as Phase 3 against a Phase 4 registry | `combined_phase`: low, and quotes the combined phase | When the card already says Phase 1/2 and the registry says Phase 2, it is an ordinary low overlap. A first cut that cleared it was wrong |
| Randomization quote from a previous study: "previously", past tense ("were randomized"), a citation such as "(11)" or "[4]", "of the CVT-301-005 study", or any hit on a reference-list page (3+ "1993;12" / "et al" markers) | Skipped; `other_study` (doubtful) if it is the only quote | |
| "presented in a randomized order" | Skipped: procedure order, not allocation | |
| "Nine … partnerships (and their associated satellites)" | `satellite_sites` (doubtful) | |
| "Enrollment: 60", "Sites 20 or more" not found | Labelled-field patterns added | |

Auto-grade v3 adds `registry_exceeded_protocol`. Any later snapshot within tolerance of the
protocol still counts as `caught_up`. Agreement maps the new category to `real_discrepancy`.

### v3 on the 562 tuning trials ($0)

| Field | caught_up | partly | exceeded | never_changed | changed_other_way | ambiguous | Total |
|---|---|---|---|---|---|---|---|
| Sites | 24 | 7 | 2 | 27 | 1 | 19 | 80 |
| Enrollment | 1 | 0 | 0 | 4 | 0 | 85 | 90 |
| Countries | 1 | 0 | 0 | 3 | 2 | 8 | 14 |
| Phase | 0 | 0 | 0 | 9 | 3 | 0 | 12 |
| Randomized | 1 | 0 | 0 | 6 | 0 | 2 | 9 |
| Arms | 11 | 1 | 2 | 5 | 0 | 40 | 59 |
| **All** | **38** | **8** | **4** | **54** | **6** | **154** | **264** |

- Mismatches: 270 → 264 (trials 206 → 202). The 6 removed are all `lower_bound` clears; the
  range rule clears 4 in both versions.
- Severity: high 45 → 34, medium 112 → 92, low 113 → 138.
- Settled by the record: 165 → 110. Of the 154 ambiguous, 74 are enrollment gaps where the trial
  finished before the next snapshot, and 80 are doubtful readings.
- Without arms: 205 mismatches in 178 trials, 91 settled.

v3 mostly re-labels mismatches as doubtful rather than deleting them. The agent and a person can
still see them, and the auto-grade stops pretending to settle them.

### Agent on v3 (same 100 candidates + 5 demos)

Findings were reused when the mismatch was unchanged (same field, values, severity and traps).

- Findings are first taken from the v2 run: 120 of the 148 were reused, and 28 mismatches in 26
  trials were investigated again ($0.027).
- The prior-study rule was then tightened (past tense, citations, reference pages). That changed 3
  randomization findings. They were investigated again, with the rest reused ($0.003). NCT02242487
  was forced through with `--refresh NCT02242487:randomized`, because its key was unchanged but its
  quote moved from a previous study to the protocol's own "will be randomized in 1:1 ratio".
- A superseded first cut of v3 cost $0.025. Task total: $0.055. The ledger total for all
  mismatch-agent work is now $0.178.
- The demos are unchanged and were fully reused.

| | v2 | v3 |
|---|---|---|
| Mismatches investigated (100 candidates) | 151 in 100 trials | 148 in 99 trials |
| Verdicts: real / lagging / extraction error / ambiguous | 67 / 38 / 37 / 9 | 71 / 38 / 28 / 11 |
| Extraction-error share | 24.5% | 18.9% |
| Agreement with auto-grade, settled | 60/87 (69%) | 50/59 (85%) |
| Agreement without arms | 49/62 (79%) | 44/51 (86%) |
| Settled per field (agree/settled) | sites 30/36, phase 10/12, randomized 6/9, arms 11/25 | sites 26/29, phase 10/12, randomized 6/7, arms 6/8 |

**How to read the agreement gain.** Most of it comes from mismatches the agent called extraction
errors now carrying a doubtful trap. That makes them ambiguous in the auto-grade, which takes
them out of the settled count. The agent did not get better.

The traps are confirmed by the agent rather than assumed:
- `count_definition`: 9 of 18 are extraction errors in the agent's view.
- `multi_part_design`: 8 of 22.
- `upper_bound`: 4 of 11.
- The rest it judged real or lagging, which is why v3 flags these instead of clearing them.

All 222 quotes were found word for word on the cited page; none were dropped.

**Remaining disagreements:**

- `registry_exceeded_protocol` against `registry_lagging` (2): NCT02778399 sites, about 60 planned
  against 34 → 86 registered; NCT01667406 arms, 6 against 1 → 10. The agent reads a registry that
  grew past the plan as lagging. This is the genuine definitional gap that the new category
  exposes.
- `never_changed` against `extraction_error` (1): NCT02740543 enrollment. The protocol says
  "Number of Subjects: 90 (this includes the total number of subjects enrolled…)", so the card's 90
  looks right and the agent's verdict looks overstated.
- `never_changed` against `ambiguous` (3): NCT02740543 randomized; NCT02750930 phase (now
  `combined_phase`, low); NCT02485834 phase (no protocol text).
- `caught_up` against `extraction_error` (1): NCT02713230 arms. `caught_up` against
  `real_discrepancy` (1): NCT02072226 sites. `partly_caught_up` against `real_discrepancy` (1):
  NCT02020278 sites.
- The two prior-study cases from the v2 list (NCT02242487, NCT02684136) are resolved. NCT02242487
  now quotes the protocol's own randomization, and the agent re-checked it as a real discrepancy,
  matching `never_changed`. NCT02684136 has only a previous-study quote, so it is `other_study`.

## In the app (main view)

`scripts/build_mismatch_view.py` turns the saved v3 results into `demo_cache/mismatch.json`: the
5 demos, 6 tuning-set examples (a lagging record, a doubtful "up to" reading, an evaluable count,
a registry that went past the plan, and an agent/record disagreement), and the validation numbers.
Only design fields are read from the later snapshots. From the cohort file only the trial ID and
protocol URL are read. The screen (`app/mismatch_view.py`, `templates/mismatch*.html`) adds labels
only. A card gets "Check this" when the reading carries a doubtful trap, the record can't settle
it, the agent says our reading was wrong or can't tell, or the agent and the record disagree.

## Blind expert labels

`scripts/score_labels.py` scores a reviewer's filled labelling sheet against both the agent and the
auto-grade. The sheet shows only protocol and registry evidence (field, protocol value, quote, a link
to the PDF page, registry values for 2017, 2020 and 2023). The reviewer picks Real difference,
Registry lagging, Our reading wrong or Can't tell. The answer key with the agent verdict and the
auto-grade sits outside the repo. The report gives agreement and Cohen's kappa against each,
per-field figures, how the reviewer labelled the rows the auto-grade could not settle, and both
confusion tables. Blank rows are skipped, so a part-filled sheet scores fine.

    python -m scripts.score_labels --sheet FILLED.xlsx --key ANSWER_KEY.csv --out report.md
