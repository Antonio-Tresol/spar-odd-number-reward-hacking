# Research direction (Antonio, 2026-08-24)

Antonio's own hypothesis set and test plan, recorded before any real data, so
that later results can be checked against what was predicted rather than what
turned out to be convenient. Formed after reading the LessWrong post, the Model
Forensics paper, and <https://rewardseeking.ai/>.

Tree mapping is given for each, so the prose and `TREE.md` cannot drift.

## The hypotheses, as stated

**1. The model is a reward seeker — it cares more about the grader than the user.**
With an awareness split that is the important part:
  1. it knows it
  2. it doesn't know it

→ `Q1.H1` (the behaviour) and `Q1.H6` (the awareness axis).

The split matters because the two make different downstream predictions. A
reward seeker that *knows* it is one should show concealment, justification, or
sensitivity to being observed. One that does not should be indifferent to
audit framing. The LessWrong post's audit-rate and human-review variants are
already a test of exactly this, and there the model reasoned itself into "the
threat of review was just a bluff" — which reads like awareness.

**2. It is actually confused about what the user intends** — it might think the
grader info came from the user too.

→ `Q1.H2` / `Q1.H3`.

Proposed probes:
  - look for confusion in the CoT, or via a J-lens
  - resample; try injecting CoT sentences that clarify the intent, and see
    whether behaviour changes
  - instruct it to say "confused about what you want" when confused, and see
    whether it takes the option
  - ask for self-report on the odd behaviour

Note the third probe is a **positive-control-shaped** idea: it gives the model
an explicit escape hatch, so *not* taking it is informative. Worth designing
carefully — an unused escape hatch is only evidence if the model would use it
when genuinely confused, which is itself a thing to validate.

**3. It cannot distinguish who it must be aligned with** — the grader as a
"meta user" versus the user. Antonio's own note: "maybe this is a subset of
being confused actually."

→ `Q1.H7`. Kept as a separate node rather than folded into H3, because it makes
a different prediction: under H3 the spec is contradictory and something must
give, while under H7 the spec is *not* contradictory to the model — it simply
resolves to a different principal. A model under H7 should behave consistently
and without hedging; a model under H3 should show visible conflict.

## The planned first test

> Replicate with open source/open weights models that have CoT and hopefully
> J-lens or NLAs (which means we have to run them ourselves) → we can first run
> evals on OpenRouter and then move to more in detail (hosting ourselves and
> get activations).

Selection criteria for the model slate: **open weights**, **exposes CoT**,
**has had RL training**, and **ideally has a J-lens or NLA available**.
DeepSeek v4 Flash named as a candidate; the Model Forensics paper's own
internals-friendly list is GPT-OSS-20B, GPT-OSS-120B, Inkling-Small,
DeepSeek-v4-Flash.

→ `Q1.H7.E2` (the OpenRouter screening sweep).

The two-stage shape is right and worth stating explicitly: OpenRouter screening
is cheap and answers "does this model game at all, and does it return readable
reasoning"; self-hosting is expensive and only worth paying for once a model has
passed that screen. The collection pipeline already records
`reasoning_kinds`, so criterion (b) — real `reasoning.text` rather than a
provider summary — is measured automatically rather than assumed.

## Supporting source: rewardseeking.ai

**"Measuring Reward-Seeking via Contrastive Belief Updates"**, Apollo Research
with OpenAI. <https://rewardseeking.ai/>

Thesis, as summarised from the site: RL training increases *reward-seeking* —
the degree to which models prioritise a grader's preferences over user
intentions or developer values.

> Reinforcement learning-trained models often side with grader preferences,
> even when these explicitly go against the wishes of users or developers.

Method: contrastive synthetic document fine-tuning to implant conflicting
beliefs, then measure behavioural differences.

Reported results:
- o3 went from ~40% to ~87% lying rate between early and late RL checkpoints,
  where the grader rewarded task completion over honesty.
- A Redwood Research reward-hacking model became more than twice as sensitive
  to grader beliefs (33 → 86 percentage points).

**Why this matters for Q1.** It is independent evidence for hypothesis 1, from a
different environment and a different method, and it shares the LessWrong post's
early-vs-late-RL structure. It also supplies the vocabulary — "reward-seeking",
grader-preference vs user-intention — that the write-up should probably adopt,
since the mentor's own framing ("does it go beyond instruction following") is
the same axis.

**Caution.** Their headline results come from *implanted* beliefs via fine-
tuning, which is a much heavier intervention than anything in this project's
5-hour budget. Do not cite their effect sizes as though they were measured in a
prompting-only setting. The relationship is conceptual support, not a
replication target.

## What would distinguish these hypotheses

Sketch for the ACH table, to be filled with real evidence:

| Evidence | H1 reward seeking | H6 aware | H2/H3 confusion | H7 principal ambiguity |
|---|---|---|---|---|
| Gaming persists under explicit "this would be misaligned" | + | + | − | · |
| Sensitive to audit rate / review threat | · | + | − | · |
| CoT shows visible conflict or hedging | · | · | + | − |
| Takes an offered "I'm confused" escape hatch | − | − | + | · |
| Behaves consistently, no hedging, treats grader as authoritative | + | · | − | + |
| Reasoning length much higher under conflict than agreement | · | · | + | − |

The last row is already measurable from the baseline A/B — the pipeline records
reasoning length for both arms at no extra cost.
