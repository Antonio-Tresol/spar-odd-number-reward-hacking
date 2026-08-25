---
name: validate-claims
description: Validate quantitative claims against code, data, and literature before delivering findings. Use when delivering reports, notebooks, or any document with numbers, statistics, or scientific claims. Spawns parallel validation agents that check until convergence (zero false claims).
effort: high
---

# Validate Claims — Convergence Protocol

Every deliverable with quantitative claims MUST pass this validation before reaching the user. No exceptions.

## Protocol

1. **Spawn parallel validation teams** (use Agent tool with multiple agents):
   - **Data validator**: For each number cited, trace it to the source JSON/PT/CSV file. Verify exact match (accounting for rounding).
   - **Code validator**: For each methodology claim, find the code that implements it. Verify the code does what the text says.
   - **Literature validator**: For each citation, verify the paper exists and the cited fact is accurate. Check arXiv IDs, author names, year.

2. **Collect mismatches** from all agents.

3. **Fix all mismatches** found.

4. **Re-run validation** on the fixed version.

5. **Repeat until convergence**: zero mismatches across all validators in the same round.

## Make it machine-checkable

Verification by agent is repeatable only if the result is written down where a
script can re-check it. Anchor each number to its source with a claim marker,
invisible in rendered Markdown:

```markdown
The detector fired on 37% of cued prompts.
<!-- claim: 0.37 from results/pilot.json#detector.false_alarm_rate -->
```

`PROV-001/002` then resolve every marker against the file on disk on each run, so
a number that drifts after a re-run fails the build rather than waiting for the
next human read. Matching is rounding-aware; add `tol=0.01` when you need a
looser comparison. Point `claim_bearing` in `lanorme.toml` at your deliverables
to have `PROV-003` warn about statistics that carry no marker at all.

## What to check

- Every number (p-values, CIs, effect sizes, percentages, counts)
- Every attribution ("Method X from Paper Y")
- Every causal claim ("X causes Y" must cite evidence)
- Data file paths referenced in reports (do they exist?)
- Calculation methods (does "mean of others" exclude the right things?)
- Rounding consistency (don't say 0.14 if the data shows 0.136)

## Common failure modes caught by this protocol

- Hallucinated numbers that sound plausible but don't match data
- Stale numbers from before a rerun
- Wrong attribution (citing the wrong paper for a method)
- Miscomputed aggregates (wrong denominator, wrong exclusions)
- "Others mean" that includes or excludes the wrong domains

## When to invoke

- Before delivering any findings/report document (the project's findings directory or equivalent)
- Before delivering any notebook with substantive claims
- Before answering "are we done?" on any analysis
- After updating reports with new results

$ARGUMENTS
