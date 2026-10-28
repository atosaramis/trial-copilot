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
| `caught_up` | The registry later reached or passed the protocol value, so it was lagging |
| `partly_caught_up` | The registry moved toward the protocol value but stayed short |
| `never_changed` | The registry kept its 2017 value (within the same tolerance) |
| `changed_other_way` | The registry changed, but not toward the protocol value |
| `ambiguous` | Can't be settled from the record (see below) |

A mismatch is ambiguous when:
- our reading is doubtful (one of the reading traps above), and the registry never later matched the protocol. If it did later match, that confirms our reading, so the mismatch counts as `caught_up`;
- for enrollment, only the planned (anticipated) number can show a correction. If the trial finished before the next snapshot, only the actual count remains. That can't show whether the plan was ever updated. The grade then records whether the actual count landed closer to the protocol or to the registry;
- there is no later record.

These categories describe what the public record did. They do not mean anyone was at fault, and they are not a compliance finding.

## Results on the 562 tuning trials with a card

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

## Next step: Muse investigation agent (not built yet, costs money)

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
