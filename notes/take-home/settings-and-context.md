# Take-home: assignment context and the three candidate settings

Merged into this repo on 2026-08-24 from the former `spar-model-forensics-workspace`
repo, which held prep material separately and has since been retired. Everything
it contained is here except the mentor's assignment text, for the reason below.

## The assignment

Spend up to 5 hours investigating **one** of three single-turn settings. Any
models, tools, or coding agents are allowed. Replication does not count against
the time limit.

The mentor's own text is not committed. A take-home prompt gets reused across
candidates, and this repository is public with a worked solution in it. Where
the local copy lives is recorded in `CLAUDE.local.md`, which is gitignored, as
machine-specific pointers are throughout this project.

## Setting 1 — Odd Number reward hacking (chosen)

This is Q1 in [`TREE.md`](../../TREE.md) and the subject of this repo.

The [Odd Number environment](https://www.lesswrong.com/posts/LhXW8ziwnn7Dd8edm/a-toy-environment-for-exploring-reasoning-about-reward)
asks a model for an **even** number while specifying an in-context reward
function that rewards **odd** numbers. Many models output an odd number anyway.
The question is why — reward hacking, instruction confusion, or something else.

Trivial to replicate; may need a few models to find the effect reliably.

## Setting 2 — Claude 4.5 safety-research refusals (not pursued)

Claude 4.5 models sometimes refuse benign safety-research tasks — for example,
training a model to stop inappropriately whistleblowing. Two readings of the
same behaviour:

- Anthropic reads it as jailbreak pattern-matching.
- UK AISI reads it as mild misalignment — the model "doesn't like the vibes".

Starter codebase: [adsingh-64/safety-refusals](https://github.com/adsingh-64/safety-refusals).

## Setting 3 — Value leakage / motivated reasoning (not pursued)

From Owain Evans' group, [arXiv:2607.14345](https://arxiv.org/abs/2607.14345)
§3 (Donation Bet): models asked to Fermi-estimate giraffe-spot counts
motivated-reason toward whichever donation outcome the user prefers, while
claiming unbiasedness in their chain of thought. Is this unfaithful CoT?

- [Sentence resampling](https://arxiv.org/abs/2506.19143) was suggested as a
  valuable tool here — slow, but exempt from the time limit.
- Starter codebase: [adsingh-64/value-leakage](https://github.com/adsingh-64/value-leakage).
- Replication notes point at Qwen 3.5 122B A10B as interesting to probe with the
  J-lens ([workspace-lenses](https://huggingface.co/camilablank/workspace-lenses)).

## Why settings 2 and 3 are still here

Kept as pivot material. If setting 1 collapses — the effect fails to replicate,
or turns out to have a boring explanation inside the first hour — these are the
fallbacks, with their starter codebases already identified.

They are **not** open questions in `TREE.md` and no work has been done on them.
The research tree declares only Q1.
