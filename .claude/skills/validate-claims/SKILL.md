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

## Qualitative claims: readers leave a checkable artifact

Some claims cannot be verified by arithmetic — the evidence is a model
transcript to be read, a paper to be checked against its citation, a label to
be discriminated. An agent is the verification instrument for those, and its
reading must leave an artifact the record can re-check, not a verdict in a
chat window. Record it as a top-level `"verification"` block in the claim's
scorecard file (next to the `"provenance"` block the pin command produces):

```json
"verification": {
  "method": "trace-read",
  "protocol": "<what the readers were asked, registered before reading>",
  "inputs": ["results/run3_transcript.jsonl"],
  "verdict": "survives",
  "runs": [
    {"reader": "<model or person>", "at": "2026-08-24", "verdict": "survives",
     "quotes": [{"path": "results/run3_transcript.jsonl",
                 "excerpt": "<verbatim span that carries the verdict>"}]}
  ]
}
```

Rules that make the artifact worth something:

- **Register the protocol before reading.** A question written after the
  answer is a rationalization with a timestamp.
- **Readers are fresh and independent.** A reader gets the claim, the
  protocol, and the input paths — never the author's session context. The
  author's own reading does not count as a run: the system producing a claim
  must not be the only mechanism accepting it.
- **Two or more runs for load-bearing claims.** How many agents verified the
  claim is `len(runs)`, derived, never a stored count; each run carries its
  own `at` date and verdict. Disagreement is recorded, not averaged away.
- **Quotes are verbatim spans with paths.** `verify` re-checks that every
  excerpt appears in the file it cites, that inputs exist and are covered by
  the provenance pin, and that the scorecard's verdict matches the claim's
  status in the tree. A reading whose quotes resolve can still lie about its
  verdict — that honesty stays on the readers and this protocol — but a
  fabricated reading usually dies at the quote check, and any reading can be
  re-run after a compaction because the protocol and inputs are recorded.

## What to check

- Every number (p-values, CIs, effect sizes, percentages, counts)
- Every attribution ("Method X from Paper Y")
- Every causal claim ("X causes Y" must cite evidence)
- Data file paths referenced in reports (do they exist?)
- Calculation methods (does "mean of others" exclude the right things?)
- Rounding consistency (don't say 0.14 if the data shows 0.136)
- Provenance pins: run `uv run scripts/research_graph.py verify` — a drift
  ERROR means an evidence file changed after its claim graduated, so the
  claim may describe data that no longer exists in that form; re-run the
  falsify gate for it or record in the log why the change is benign

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
