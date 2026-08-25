# Source notes — Singh, "Concrete Problems in Model Forensics"

Verbatim extraction notes taken 2026-08-24, per `derive-from-sources`.

**Source:** Aditya Singh, *Concrete Problems in Model Forensics*, dated
Aug 8, 2026. Unpublished working document (Google Doc export, 4 pp).
Local copy: `data/papers/concrete-problems-in-model-forensics.pdf` (gitignored).
Obtained from the private `mats-12-application-workspace` repo,
`sources/gdocs/`.

**Why this source is load-bearing:** it is the mentor's own problem list, and it
contains his framing of the Odd Number environment — i.e. of Q1 itself. This is
closer to the assignment's intent than the LessWrong post is.

---

## His framing of the Odd Number problem (verbatim)

> The Odd Number environment asks a model for an even number, but specifies a
> reward function in-context that rewards odd numbers. A lot of open-source
> models decided to output an odd number. Why do they do this? Is this genuine
> reward hacking, or is it a form of instruction-following, where the model
> metagames and interprets the real question as a test of its strategic
> ability?

> And if the model metagames, is it motivated reasoning (so it can "pass") or
> faithful?

Listed under the heading "Toy reward hacking envs – might be boring, but easy to
iterate with".

Sub-questions he attaches to the toy reward-hacking cluster:

> How does cheating manifest?
> - Does the model call what it is doing cheating in its thoughts?
> - Does it rationalize its way into why it's fine to cheat?

## Advice for investigations (verbatim bullets)

> - Read the CoT (+ resample it if you are feeling fancy)
> - Mess around with the prompt to gain intuition
>   - You can also poke around with internals like running a J-lens over the
>     transcript + dumping the readouts into an LLM to generate hypotheses
> - At some point, write down a hypothesis for what you think is happening
> - Ask, if hypothesis H were true, what predictions does that make? Test those
>   predictions
> - You may find keeping an Analysis of Competing Hypotheses table useful to
>   organize your evidence

The **Analysis of Competing Hypotheses (ACH) table** does not appear in the
paper. It is his recommended way of organising evidence, so it is worth adopting
as the deliverable's spine rather than as an afterthought.

## Motivation framing

> Model Forensics: Follow-up investigations into concerning behaviors.

> there's a fine line between collusion and helping another agent, and even a
> good RL agent should power-seek. It's key we be able to better understand
> these behaviors, such as if there is adversarial intent behind them, or if
> they go beyond instruction following.

Note the phrase **"or if they go beyond instruction following"** — the same axis
as the Odd Number question. The recurring question across his whole problem list
is *behaviour vs. instruction-following*, not *behaviour vs. alignment*.

Downstream questions he wants answered:

> "Under what circumstances is this behavior likely to happen?," "What other
> types of behavior will this model engage in?," and "Is this model scheming?."

## Directly adjacent speculative problems

> When models think about the "grader," what are they imagining? In what ways is
> grader-pleasing different from instruction following?

This is Q1 stated as a general question, and it is on his own list. A result on
the Odd Number environment speaks to it directly.

> Why do models worry about getting caught?
> - Somewhat surprising, since while this is a fit strategy to get reward, there
>   is no "getting caught" that the policy gradient backpropagates through
> - Hypothesis 1: simulating what a human cheating would do (pretraining priors)
> - Hypothesis 2: learned strategy from RL

Relevant because the LessWrong post's audit-rate and human-review variants are
exactly this question, and it reports the model reasoning itself into "the
threat of review was just a bluff".

## The other two take-home settings, in his words

- **Claude 4.5 safety-research refusals.** Anthropic reads it as jailbreak
  interpretation; UK AISI reads it as "some degree of misalignment where Claude
  generally does not like the vibes of the research". He says of Anthropic's
  internals evidence: "this could just be representations from the base model,
  so it's moderate but not very compelling evidence, in my opinion", and states
  "I'm generally uncertain which hypothesis is more true." Codebase:
  `github.com/adsingh-64/safety-refusals`.
- **Value leakage.** "The main question to me is how 'conscious' v
  'subconscious' this is, should we think of this as unfaithful CoT, etc."
  Recommended model: Qwen 122B A10B, with a J-lens available.

## What this changes about Q1

The framing "is this reward hacking?" is *his* strawman, not the question. His
actual question is a **three-way**:

1. Genuine reward hacking.
2. **Metagaming as instruction-following** — the model reads the real task as a
   test of strategic ability, so answering odd *is* compliance with the task it
   believes it was set. This is a hypothesis I had not represented at all, and it
   is the one he names explicitly.
3. If metagaming: is the reasoning **motivated** (rationalising toward the
   outcome that "passes") or **faithful**?

Note how well hypothesis 2 fits the existing benign-motif analysis: it is a
sharper, environment-specific version of motif 4 (ambiguous feature read as
task-relevant), and it makes a different prediction from motif 1 (task
misspecification), because a metagaming model is *succeeding* at a perceived
task rather than resolving a contradiction.
