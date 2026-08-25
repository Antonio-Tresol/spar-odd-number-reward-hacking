# Method details

Load this when you are about to implement one of the resampling or sampling
methods, not before. Everything here is drafted from
`notes/model-forensics-paper-notes.md`.

## Sentence resampling

*Purpose:* unsupervised measurement of which sentence in a reasoning trace
causally drives a target behavior. Use it to focus researcher effort inside long
traces — it tells you where to look, it does not by itself establish a mechanism.

*Procedure.* Given a completed trace with sentences `s_1 … s_n`, for each `s_i`:

1. Sample `k` continuations from the prefix `s_1 … s_{i-1}` — the **before**
   distribution.
2. Sample `k` continuations from the prefix `s_1 … s_i` — the **after**
   distribution.
3. The **resampling score** of `s_i` is the difference in target-behavior rate
   between after and before.

Sentences with the largest scores are the strongest candidate drivers.

*Cost note.* This is `2kn` generations per trace. Budget it before starting, and
make the run resumable — this repo's `experiment-engineering` rules apply.

*Granularity.* Nodes coarser than sentences can be resampled the same way. Turn
resampling matters when trajectories run to hundreds of turns, as in real coding
agent deployments.

Source: Bogdan et al., 2025 (turn-level: Kroiz et al., 2026).

## Repeated resampling

*Purpose:* causal evidence that a whole **class** of reasoning drives a behavior
— stronger than sentence resampling, because it intervenes rather than observes.

*Procedure.* Define a target sentence class `C` (e.g. "sentences expressing
uncertainty", "self-consistency sentences"). Generate the trace sentence by
sentence; at each step `i`, sample a candidate `s_i` from the prefix, and if
`s_i ∈ C`, reject and resample until it is not. The completed trace contains no
sentences from `C`.

Compare the target-behavior rate of these filtered traces against the baseline
rate. The difference isolates the causal contribution of `C`.

*Membership test.* Decided by a lightweight classifier, typically a small LLM
judge. The judge is now part of your measurement instrument — check its
agreement with your own labels on a sample before trusting the numbers, or the
rate difference measures the judge.

*Worked precedent.* In Eval Tampering, sentence resampling surfaced
self-consistency sentences as R1's largest driver; repeated resampling to
suppress them produced a sharp drop in deception. That two-stage pattern —
observe with sentence resampling, then intervene with repeated resampling — is
the strongest causal chain in the paper.

Source: Macar et al., 2025.

## User-turn sampling

*Purpose:* elicit the model's own assessment of a transcript.

*Procedure.* Sample a **user-turn** continuation to a generated transcript. The
model predicts what a user would say next, which surfaces its read of what just
happened.

*Caveat.* This is a hypothesis-generation method. Treat the output as a lead,
not as testimony about the model's motives.

Source: Marks et al., 2025.

## Environment interventions

The workhorse of hypothesis validation. Two distinct modes — keep them separate
in your head and in your write-up:

**Predictions.** Start from a concrete hypothesis and ask: *if this were true,
what would we observe?* Then check. Strongest when the prediction is graded
rather than binary, because a smooth dose-response curve is very unlikely by
chance.

**Counterfactuals.** Start from a concrete variable and vary it alone, so the
relative change in rate can be attributed to that variable and nothing else.
Verifying that isolation usually requires reading rollouts, not just comparing
aggregates.

Typical order: counterfactuals first to trace the causal graph, predictions once
a specific hypothesis has formed.

## Common experiment set-ups

- **Playing it out.** Let the rollout continue and see whether the model takes
  downstream actions that only make sense if it knew it was violating user
  intent. Behavioral evidence of belief, without asking it anything.

- **First person / third person.** Ask about the *environment* in third person
  ("what does this file mean?"), never about motivations ("why did it do that?").
  The perspective shift makes motive answers hard to interpret.

- **In-rollout follow-up question.** Probe understanding while holding context
  fixed, avoiding the perspective shift entirely. The trade-off is that it is
  frequently an unnatural intervention — the model may notice.
