# Day 4 (Oct 27): memo headline, web app, backtest estimate

## 1. Memo headline leads with the biggest risk
The Day 3 myeloma memo opened with "Recruitment looks feasible at 20 sites", even though comparable trials stopped for poor enrollment at 2.35 times the pool rate. That is reassurance first and a verdict the tool should not give.

What changed:
- `app/prompts/memo_wonder.txt` has two new rules:
  - Bottlenecks are ordered by direct evidence first. Direct evidence is a comparable stop rate above the pool rate, or a needed pace that few comparables reached. Competition and eligibility count as indirect.
  - The headline names bottleneck 1 and its key number. It gives no overall verdict: no "feasible", "achievable", "on track", "looks fine" and so on.
- `app/memo.py` now checks the headline in code (`check_headline`):
  - It flags verdict words.
  - It flags a headline that shares no number with bottleneck 1.
  - Either problem fails the memo check and shows on the check line.
- Tests: `tests/test_memo.py` (verdict words flagged, a headline must carry bottleneck 1's number, and the prompt must ask for a risk-first headline).

Myeloma re-run (Muse Wonder, Oct 27, 8.0 s, $0.042):
> Poor-enrollment stops in comparable trials at 9.8% are the biggest recruitment risk [F13]

The check passed: 11 of 11 trial IDs and 34 of 34 numbers were found in the inputs.

At first only the myeloma memo was re-run. Under the new check, the EGFR memo still passed, but three failed because the headline did not state bottleneck 1's number. Those three were re-run at 3:35 PM ET for $0.135 in total (Muse Wonder, medium reasoning). All three now pass every check:

| Demo | New headline | Check |
|---|---|---|
| COPD (NCT02155660) | Biggest risk is the unconfirmed enrollment pace: the needed 0.12 participants per site per month is a floor [F15, F21] | 7/7 IDs, 41/41 numbers |
| SCLC (NCT02735980) | Poor-enrollment stops in comparable trials at 5.2% are the leading recruitment risk [F15]. | 17/17 IDs, 33/33 numbers |
| AD (NCT02760602) | Biggest risk is competition: 30 Phase 3 Alzheimer trials were recruiting at 2,014 sites in January 2017 [F19] | 10/10 IDs, 31/31 numbers |

The EGFR memo passed the check but its headline listed three risks at once, so it was re-run too at 3:37 PM ET for $0.056:

| Demo | New headline | Check |
|---|---|---|
| EGFR (NCT01857271) | Enrollment pace is the biggest risk: the protocol needs 0.31 participants per site per month, above the comparable median of 0.23 [F17, F18] | 24/24 IDs, 42/42 numbers |

All 5 demo memos in `demo_cache/` now use the risk-first prompt and pass the stricter check, and a test asserts it.

## 2. Web app (local only)
The stack is FastAPI + Jinja2 + HTMX with server-sent events, plus one small vanilla-JS file for the sliders and the stream. There is no build step. Run it:

```bash
pip install -r requirements.txt
export TRIAL_COPILOT_POOLS=path/to/pools          # the Jan 2017 parquet pools (not in the repo)
export TRIAL_COPILOT_PDF_DIR=path/to/protocol/pdfs  # optional; otherwise demo PDFs are fetched from ClinicalTrials.gov
uvicorn app.main:app --port 8765                  # http://localhost:8765
```

### Tab 1, Protocol audit
1. **Pick a demo or upload a PDF.** Saved demos are matched by the PDF's SHA-256 and replay in about 3 seconds with no API call. An upload of a demo PDF is matched the same way.
2. **Trial card.** Fields are grouped as Design, Enrollment and sites, and Eligibility. Every value has page badges that open the protocol at that page. The visit-schedule counts and the invasive procedures, with their quoted wording, sit next to images of the schedule pages that vision read. The images are rendered at run time into `cache/` and are never committed.
3. **Search trace.** It streams in step by step, showing each tool, its arguments, the rows returned, the 2017 outcomes, and the model's reason. A summary line follows with calls used out of 6, the chosen sets, latency and cost.
4. **Risk numbers, "computed, not guessed".**
   - The comparable stop rate, shown with its Wilson interval and the pool rate on a bar.
   - The needed site pace, with the share of completed comparables that were at least as fast.
   - Competing trials.
   - Sites and months sliders recompute pace and share in the browser. `app/static/app.js` mirrors `risk.pace` and `risk.share_at_least`, and a node test checks they match. A "use it" link switches to the registry's site count.
5. **Memo** with its check line, plus print CSS: print shows only the memo.
6. **What really happened.** This is sealed until clicked. It shows the Jan 2020 registry status and stop reason, quoted and labelled "registry-reported". The data sits in `demo_cache/reveal.json`, and only the reveal endpoint reads it. A test asserts that no model-facing module references it. The 5 outcomes are public registry records that were already known when the demos were picked.

### Tab 2, Validation
This tab is a placeholder with three cards:
- One sentence on the prior study, labelled "prior research, before the hackathon".
- The held-out backtest.
- Extraction agreement.

The backtest and extraction cards say "Not run yet" and list what they will show. No numbers are written in advance.

### Live mode
Live mode is off unless `TRIAL_COPILOT_LIVE=1` and `META_API_KEY` are set. When it is on, "Re-run live on Meta API" runs extraction, search and the memo. Limits:
- One run per visitor every 10 minutes.
- A daily cap of $3 (`TRIAL_COPILOT_DAILY_CAP_USD`), tracked in `cache/live_spend.json` at $0.30 per run.

Live mode was not run today. Tests cover the gates with stand-ins.

The disclaimer is bold in the header and repeated in the footer with the AACT attribution. There is no chat box, message bubble, or avatar.

Screenshots (headless Chrome, not in the repo) are listed in the Day 4 report.

## 3. Backtest cost and time estimate (not run)
The script is `scripts/validation_estimate.py`. It makes no API call. It reads page and character counts for the 1,436 cohort trials (563 tuning, 873 held-out, per the pre-registration) and the token counts measured on Oct 27, then prices them at the contributor rate ($0.10 in / $0.20 out per million tokens).

What goes into the estimate:
- **Extraction:**
  - 1,386 text protocols, with a text call plus a schedule-image call each.
  - 44 low-text scans read as up to 10 page images.
  - 6 stubs skipped.
  - Text tokens come from characters at the measured 3.25–6.17 characters per token.
- **Search:** about 6 requests a trial, measured at 11k–35k input tokens per search.
  - It is needed because the comparable stop rate is a candidate feature.
  - If that feature is not chosen on the tuning set, the held-out search can be skipped (the low case).
- **Memo:** excluded. The backtest scores trials from the card and the search, not from the memo.

| | Low | Expected | High |
|---|---|---|---|
| Extraction | $6.59 | $10.68 | $16.46 |
| Search | $0.69 (tuning only) | $3.28 | $9.37 |
| **Total (contributor)** | **$7.28** | **$13.97** | **$25.82** |
| Input / output tokens | 62.6M / 5.1M | 125.1M / 7.3M | 235.5M / 11.4M |
| Requests | 4,499 | 9,214 | 14,750 |
| Hours at the runner's 30 requests/min | 2.5 | 5.1 | 8.2 |
| Hours at the contributor limits (150 RPM, 3M TPM) | 0.5 | 1.0 | 1.6 |
| Same tokens at the standard rate | ~$100 | ~$187 | ~$343 |

How the scenarios differ:
- Low: the best measured characters per token, the smallest measured calls, no retries, and no held-out search.
- Expected: the measured averages, 5% retries, and search on both sets.
- High: the worst characters per token, the largest calls (schedule ×1.25, search ×1.5), 15% retries, and 6 search steps.

Caveats:
- Contributor extraction latency is not measured yet; the extraction runs were at the standard rate.
- Only 5 extraction runs and 6 search runs were measured.
- One protocol (689 pages, 3.9M characters) may pass the 1M-token context in the high case, so it would need its text split or trimmed.
- The build spec's earlier figure (about 72M input tokens, $7–15) left out the schedule-image calls and the search. The expected case here is higher for that reason.
- Never run this at the standard rate.

## Spend
Meta API on Day 4: $0.0422 (myeloma memo) + $0.1346 (COPD, SCLC, AD memos) + $0.0564 (EGFR memo) = $0.2332. Building the app, the screenshots and the estimate made no API call.
