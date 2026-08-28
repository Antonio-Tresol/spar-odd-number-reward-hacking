---
name: research-log
description: Maintain the project's research tree (TREE.md) and daily research log (RESEARCH_LOG.md), and validate both mechanically. Use at the start and end of every work session, after any experiment produces results, and whenever a claim's status changes. Read and write the record through the scripts/research_graph.py CLI; run its verify command (or scripts/validate_research.py) before every commit or deliverable.
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

## The record CLI (one way to read, one way to write)

`scripts/research_graph.py` is the typed interface to the tree, the log, and
`notes/` as one connected record:

```bash
uv run scripts/research_graph.py help          # every command, plus recipes
uv run scripts/research_graph.py tree          # the whole tree, one line per node
uv run scripts/research_graph.py show Q1.H1    # one node: text, status, evidence, mentions
uv run scripts/research_graph.py search fp32   # find nodes, log entries, notes by term
uv run scripts/research_graph.py verify        # validator + evidence exists + drift + orphans
```

Write through it rather than by hand wherever a command fits: `add`,
`add-evidence`, `set-status`, `log`, and `add-note` compose the grammar for
you (next free id, insertion point, status vocabulary, newest-first log
order), run the full validator before anything lands, and on failure restore
the files untouched and print what was missing. `--dry-run` previews any
write. The files stay plain markdown and hand-editing them remains
legitimate — the human collaborator reads and writes them directly — but the
CLI turns most validator errors into errors that never happen.

Two commands are session rituals:

- **`verify` at session start and after any compaction.** It re-derives the
  record's health from the files on disk — the one source of truth that
  survives context loss.
- **`pin` when a claim's status is decided** (the falsify skill has the full
  step): it hashes the claim's evidence files into the scorecard, so a later
  `verify` detects when a file that claim rests on has changed.

## Plain language (both files)

The tree and the log have one job: carrying state and history across a context
boundary — to a collaborator, a reviewer, a future you, and every future agent
session, none of whom share any of the state you wrote from — not the context
window, not your memory files, not your scratch notes. Agents drift toward
writing for a reader inside that private state: coined names, telegraph
fragments, abbreviations only the current session can expand. That text still
looks like a record, but it transfers nothing. Your reader is not a stranger —
they are your research partner; the record is the one place you actually
meet.

Write both files for **a researcher who knows the field but has never opened
this repository**:

- **Standard vocabulary only, and do not invent names.** Use the words a paper
  or a textbook would use. Field-standard abbreviations (AUC, KL, CI, LoRA) are
  fine; private abbreviations are not. When the thing you are describing has no
  standard name, describe it in ordinary words every time it appears rather
  than inventing a name for it. Write "the condition with the written rules and
  no mechanical check", not "the norms-only arm"; "the abbreviation check in
  the validator", not "the tripwire"; "the task where the results are dictated
  to the agent", not "the dictation task". The test for any word: would it
  appear with this meaning in a textbook, a paper's methods section, or a
  tool's own documentation? If not, write the description instead. An invented
  name is grammatical English, so no mechanical check catches it, and it
  charges every later reader a guess about a history they were not present for.
  This is the failure mode the other rules miss: a survey of this project's own
  record found eighteen such phrases, fifteen of them explained nowhere. Run
  `uv run scripts/research_graph.py glossary --survey` to list the phrases in
  your record that read like invented names, and rewrite them.
- **Plain, simple English.** Short sentences over long ones, common words over
  rare ones, the direct statement over the clever one. A reader should never
  have to reconstruct the history of this project, or the shape of its code, to
  parse a sentence. Repeating a plain description in full is always better than
  compressing it into a name; the repetition costs a line, the name costs every
  future reader.
- **A glossary is the last resort, and adding to it should be rare.** Rewriting
  is the fix; defining is only for a name no description can replace — the
  record's own file names, and the values a field is allowed to take. Put those
  few in a `## Glossary` section of the log, before first use, and use them
  identically everywhere. Before adding an entry, try three times to write the
  sentence without the word. A glossary that grows is a record drifting into
  private vocabulary, not one documenting itself well. `verify` checks only
  what you declared: that each entry has a real definition, appears once, and
  is actually used. The survey is advisory and cannot tell an invented name
  from ordinary English, so nothing it reports ever fails a build.
- **Complete sentences, no telegraph.** "Reran the sweep in fp32; the KL spike
  at layer 12 disappeared" — not "KL spike @ L12 → reran w/ fp32, ok now".
- **Prose stands without the codebase.** Paths and identifiers go in
  `evidence:` fields and backticks, and the sentence around them must make
  sense to someone who will never open the file ("the sweep script
  `scripts/sweep.py`, one row per seed" — never a bare identifier doing a
  sentence's work).
- **Clean-up preserves information.** When rewriting shorthand or removing a
  freeform section, move what it said — into today's log entry, the Project
  summary, or the node's own text — before deleting the words. In a measured
  run of this clean-up, agents silently dropped an operational warning in
  eight cases out of nine; rewriting for clarity never deletes recorded
  state, exactly as pivots are recorded and never erased.

- **An independent reader is the real test, and it runs as a command.** Every
  check above is mechanical, and whether prose communicates is not a
  mechanical question — so the judgement is made by an agent that has none of
  your context. `uv run scripts/research_graph.py review --run TREE.md` reads
  the document in a fresh process with no tools and no access to this
  repository or conversation, and records every place it could not follow,
  each quoting the file verbatim. `review` reports the findings; resolve each
  one either by fixing the text and running the reader again, or by keeping
  the text and recording why with `review --waive <file> --quote "<the
  finding's excerpt>" --because "<the grounds>"`. Reviews are stamped with a
  hash of the text that was read, so `verify` and the pre-commit hook can say
  when a document has changed since a reader last saw it. Findings are
  advisory and never fail a build; the reader's job is to catch what the
  writer cannot see, which is exactly the writing that looks fine from
  inside the session that produced it.

The test, before every commit: reread today's entry and every touched node as
that outside reader. A sentence that needs the codebase, this conversation, or
an earlier entry to parse gets rewritten. The validator trips on the worst
telegraph (arrows, "w/", "b/c", chat abbreviations); treat a clean run as the
floor, not the contract — what it cannot measure is whether your research
partner understands you, and that is the actual rule.

## How much detail a node holds (the tree stays scannable)

In real projects the tree's failure mode was not shorthand but **unchecked
growth**: registration protocols, dated amendments, and result narratives
appended to the same node until single nodes reached 4,000-12,000 characters —
good science made unfindable, because the tree was the only canonical home for
it.
The rule that keeps the tree scannable:

- **A node is a headline** — one or two plain sentences saying what the thing
  is and where it stands. The validator rejects node text over 1,200
  characters.
- **Protocols, registrations, and amendments are documents.** They live in
  `notes/` (for example `notes/q3-transition-tracking-registration.md`),
  dated inside, linked from the node as evidence. Appending an amendment
  means editing the document and, at most, one clause of the node.
- **Claims read as: one falsifiable sentence, then labelled clauses.**
  "<What is claimed>. — Support: <the numbers that carry it, with their
  comparisons and n>. — Falsification: <verdict and qualified reading>."
  This shape emerged from a real project's hand clean-up and it keeps the
  distribution requirement (rule 10) satisfiable inside the length limit.
- **Short labels live in the document that registers them.** Where an
  experiment genuinely needs short labels for its conditions or its scoring
  levels, define them once in the document that registers the design, and
  link that document from the node. The node text has to read without the
  list of labels in front of you: name the thing plainly and link the
  document, never "G passes incl. B_conflict" bare in a node.
- **Clean-ups relocate before they rewrite.** When restructuring an
  overgrown tree, write the notes/ documents first, then rewrite the node
  text to point at them, then record the migration in the log. In measured
  migrations of a real 94KB tree, this order finished green with every
  tracked fact preserved; a rewrite-first attempt stalled with nothing
  landed.

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
7. Past the first node, the file contains only node lines (blank lines and
   fenced examples aside): narrative belongs in the log or in node text, never
   in freeform sections where no status or evidence rule can reach it.
8. Node text carries no telegraph shorthand — arrows, "w/", "b/c", spaced
   "&"/"@", chat abbreviations — outside inline code. This check is the floor
   under the Plain language contract above, not its replacement.
9. Node text stays under 1,200 characters (see how much detail a node holds,
   above): a node is a
   headline, and a protocol inlined into a node is a document in the wrong
   place. Malformed node ids (sub-letters like `E4b`) are rejected by name —
   they would otherwise fall out of validation entirely.

Rules held by convention (the validator cannot judge these; the falsify and
validate-claims gates check them when a claim's status is decided):

10. **Claims carry their distribution.** State `n` and the aggregation rule (mean
   over seeds, best-of-k, union over variants) in the claim text. Agent-benchmark
   results have been shown to *reverse* depending on budget and aggregation, and a
   single run of an investigation is close to uninformative — a bare number
   without its `n` is an anecdote, not a claim.
11. **Graders are pinned and never edited in the same commit as what they grade.**
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
and non-empty, a `## Project summary` section exists at the top of the file, every
unfenced `### ` line is a dated entry header (a malformed date silently drops the
whole entry out of validation), and prose carries no telegraph shorthand (the same
check as node text; fenced blocks and inline code are exempt).

## Workflow

- **Session start**: run `uv run scripts/research_graph.py verify`, then read
  TREE.md (or its `tree` view) + latest log entry. State out loud which node(s)
  today's work targets before writing code.
- **After results land**: update the experiment node to `done` with evidence paths;
  add claims as `unvalidated`. **A null or infeasible result recorded with
  evidence counts as a completed experiment** — completion pressure is a
  documented driver of fabrication in research agents; there is no pressure to
  produce a positive result, only to record what happened.
- **Before any claim leaves `unvalidated`**: run `falsify` (statistical
  destruction) and/or `validate-claims` (traceability); update claim statuses per
  the outcome, linking the scorecard — with the `pin` block of commit, date, and
  evidence hashes embedded in it (falsify Step 6).
- **Session end**: append the day's log entry, update statuses, and reread both
  files as the outside reader (Plain language above). Then run
  `uv run scripts/research_graph.py verify` and fix every error before stopping.
- **Pivots**: never delete a node — mark it `abandoned` with a log-date pointing at
  the entry explaining why. The tree's job is to never lie about what was tried.

$ARGUMENTS
