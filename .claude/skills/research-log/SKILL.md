---
name: research-log
description: Maintain the project's research tree (TREE.md) and daily research log (RESEARCH_LOG.md), and validate both mechanically. Use at the start and end of every work session, after any experiment produces results, and whenever a claim's status changes. Run scripts/validate_research.py before every commit or deliverable.
---

# Research log + tree

Two append-friendly documents plus one validator keep the project honest:

| File | Role | Unit |
|------|------|------|
| `TREE.md` | The research tree: questions → hypotheses → experiments → claims, each with status and evidence links | Node |
| `RESEARCH_LOG.md` | Daily narrative log (BlueDot 4-question format), newest first | Dated entry |
| `scripts/validate_research.py` | Mechanical validator for both | — |

The tree is the **state** (what we believe now and on what evidence); the log is the
**history** (what was done and learned, frozen per day). Never encode state only in
the log or history only in the tree.

## TREE.md grammar (enforced by the validator)

Nodes are nested markdown list items. Each node: `- <ID>: <text> [<status>]`
optionally followed by ` | evidence: <path>[, <path>...]` and ` | log: YYYY-MM-DD`.

ID scheme (parent's ID is always a prefix):

- `Q1`, `Q2` — research questions (top level)
- `Q1.H1` — hypothesis under Q1
- `Q1.H1.E1` — experiment testing H1
- `Q1.H1.E1.C1` — claim produced by E1

Status vocabulary (exact strings, nothing else):

- Questions: `open` | `answered` | `abandoned`
- Hypotheses: `open` | `supported` | `refuted` | `abandoned`
- Experiments: `planned` | `running` | `done` | `abandoned`
- Claims: `unvalidated` | `survived` | `weakened` | `failed`

`refuted`, `failed`, and `abandoned` are healthy terminal states, not outcomes to
avoid: they mean the process caught something. A tree containing only `supported`
and `survived` nodes is a red flag (nothing was genuinely tested), not a success.

Rules the validator enforces (each one mechanically checked, exit 1 on violation):

1. IDs unique; every child's ID extends its parent's ID and is defined above it.
   (Indentation is cosmetic: hierarchy lives in the ID prefixes.)
2. Statuses come from the vocabulary for that node type.
3. Every `done` experiment and every claim not `unvalidated` has at least one
   `evidence:` path, and every evidence path exists on disk.
4. Every `supported`/`refuted` hypothesis has at least one child claim that is
   `survived`/`weakened` (belief changes require validated evidence).
5. Every node with a `log:` date has a matching entry in `RESEARCH_LOG.md`.
6. A claim may only be `survived`/`weakened`/`failed` after the falsify or
   validate-claims protocol ran. Mechanically enforced: at least one evidence
   path must be a scorecard artifact whose filename contains `falsify`,
   `scorecard`, or `validation`.

Rules held by convention (the validator cannot judge these; the falsify and
validate-claims gates check them when a claim graduates):

7. **Claims carry their distribution.** State `n` and the aggregation rule (mean
   over seeds, best-of-k, union over variants) in the claim text. Agent-benchmark
   results have been shown to *reverse* depending on budget and aggregation, and a
   single run of an investigation is close to uninformative — a bare number
   without its `n` is an anecdote, not a claim.
8. **Graders are pinned and never edited in the same commit as what they grade.**
   If a validator, scorer, or rubric changes alongside the experiment it certifies,
   the certification means nothing. Agent benchmarks have been broken in exactly
   this way, by an agent with write access to its own test files.

## RESEARCH_LOG.md format (enforced by the validator)

Newest entry first. Each entry:

```markdown
### YYYY-MM-DD

* What I did:
* What I expected vs what happened:
* What this changes about my thinking:
* What I will do next:
```

Validator checks: header dates parse, strictly descending, all four bullets present
and non-empty, and a `## Project summary` section exists at the top of the file.

## Workflow

- **Session start**: read TREE.md + latest log entry. State out loud which node(s)
  today's work targets before writing code.
- **After results land**: update the experiment node to `done` with evidence paths;
  add claims as `unvalidated`. **A null or infeasible result recorded with
  evidence counts as a completed experiment** — completion pressure is a
  documented driver of fabrication in research agents; there is no pressure to
  produce a positive result, only to record what happened.
- **Before claims graduate**: run `falsify` (statistical destruction) and/or
  `validate-claims` (traceability); update claim statuses per the outcome, linking
  the scorecard.
- **Session end**: append the day's log entry, update statuses, then run
  `python scripts/validate_research.py` and fix every error before stopping.
- **Pivots**: never delete a node — mark it `abandoned` with a log-date pointing at
  the entry explaining why. The tree's job is to never lie about what was tried.

$ARGUMENTS
