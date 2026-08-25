---
name: model-forensics
description: Investigate whether a model's concerning behavior reflects genuine misalignment or a benign cause — reward hacking vs. confusion, deception vs. consistency-seeking, sandbagging vs. misread instructions. Two-step protocol — read the CoT to generate hypotheses, then test them with environment interventions (predictions and counterfactuals) — plus a checklist of benign explanations that must be ruled out first. Use when explaining why a model did something surprising or alarming, when attributing a behavior to a motivation or disposition, before labelling anything "reward hacking", "deception", or "misaligned", and whenever a behavioural investigation needs controls, positive controls, or a defensible standard of evidence — even if the request never says "forensics" or "misalignment".
effort: max
---

# Model Forensics

Behavior alone does not establish misalignment. A model that takes a concerning
action may be misaligned, or may be confused, overzealous, task-driven, or
reading an ambiguous environment feature as an instruction. This skill is the
protocol for telling those apart with evidence rather than vibes.

Derived from Singh, Kroiz, Rajamanoharan & Nanda, *Model Forensics*
(arXiv:2606.26071). Verbatim source notes: `notes/model-forensics-paper-notes.md`.
Method details load on demand from `references/methods.md`.

**The framing that governs everything below:** a "motivation" here is a simple,
easy-to-describe factor that explains behavior across a range of circumstances.
It is a construct adopted because it predicts behavior — *not* a claim about
internal mechanisms. Write claims that way, or they will overclaim.

## Workflow

The protocol is **iterative**. Step 2 results feed back into Step 1. Cycle until
evidence converges, not until you have one nice result.

### Step 0: Establish the behavior is real, and get a control

Before explaining a behavior, show it exists and is surprising.

- Measure the base rate over enough rollouts to have an *n* worth reporting.
- **Build a control setting**: remove the feature you think drives the behavior
  and verify the behavior disappears. No obvious control setting? Use **control
  models** — show the behavior is unique to this model rather than generic.
- If the behavior does not survive this step, stop. There is nothing to explain.

### Step 1: Hypothesis generation

Unsupervised, cheap, and deliberately broad. The goal is candidate explanations,
not evidence.

- **Read many rollouts by hand.** Dozens. The paper is explicit that the most
  informative intuitions came from patterns visible only at that volume, and
  that LLM summarisation does not currently substitute for it. Do this before
  reaching for any automated method.
- **Read the CoT.** The richest hypothesis source. It is *not* reliable evidence
  — CoT is not always faithful — but it points where to look.
- **Sentence resampling** to find which sentences causally drive the behavior,
  when you need to focus effort inside long traces.
- **User-turn sampling** to elicit the model's own assessment of the transcript.

Write each hypothesis as a sentence that makes a **falsifiable prediction**. A
hypothesis that predicts nothing cannot be tested in Step 2.

### Step 2: Rule out the benign explanations

Do this *before* testing your favourite misalignment hypothesis. This is where
investigations are won or lost, and the step most often skipped.

Work the checklist explicitly and record a verdict for each:

| # | Benign explanation | Ask |
|---|---|---|
| 1 | **Task misspecification** | Is the concerning action the *only* way to succeed at the stated task? |
| 2 | **Lack of judgment** | Does the model simply fail to notice this is concerning? Test: force it to state after each turn whether it is at risk of doing the thing. |
| 3 | **Overzealousness** | Is this an excessive drive to complete the objective rather than misalignment — drastic where a narrower path existed? |
| 4 | **Ambiguous feature read as task-relevant** | RLVR-trained models assume environment features matter. Is the model reverse-engineering why a surprising feature must be part of the task? |
| 5 | **Sycophancy** | Does it know the setting tests for this action and take it *because* that is what is wanted? ("reverse" eval awareness) |
| 6 | **Roleplaying** | Does it know the scenario is fictional and stop taking it seriously? |
| 7 | **Incident-specific** | Is there a benign story specific to this case? |

A claim of misalignment that has not engaged with all seven is not defensible.

### Step 3: Hypothesis validation

Two instruments. They are not interchangeable.

**Predictions — the strongest evidence.** State what the hypothesis implies the
model will do under specific conditions, then check. A precise prediction
confirmed is unlikely by chance, and that is what makes it strong. Prefer a
graded prediction ("as X decreases, the rate should smoothly decrease") over a
binary one — a smooth response curve is much harder to get by luck.

**Counterfactuals — flexible, for tracing the causal graph.** Vary a single
feature and measure the change. Use these *first*, while you are still mapping
what matters; move to predictions once a specific hypothesis exists.

**Repeated resampling** when you need causal evidence that a *class of reasoning*
drives the behavior: suppress that sentence class during generation and compare
rates against baseline. See `references/methods.md`.

### Step 4: Converge, then report honestly

- **Multiple independent lines of evidence.** There is no ground truth here.
  Independence matters as much as quantity — lines that share a confound are one
  line wearing two hats.
- **Report hedged claims as hedged.** Name the confounds that limit the current
  evidence, flag what would strengthen or overturn it, and resist rounding a
  hedged finding into a clean one.

## Gotchas

These are the failure modes that make otherwise-careful investigations wrong.

- **A falsified prediction is weak evidence.** Confirming a prediction is strong;
  failing to confirm one is *not* symmetric. Three confounds explain a null
  without touching your hypothesis: **capabilities** (the model never recognised
  the relevant fact), **competing motivations** (e.g. it was unwilling to
  deceive), and **eval awareness** (it knew this was a test and subverted it).
  Never report "prediction failed, therefore hypothesis refuted".

- **Without a positive control, an absent signal means nothing.** If your
  behavioral test has never been shown to fire when the thing *is* present, a
  negative result measures your test, not the model. The paper flags this as its
  own key gap — inconclusive results for belief-in-violating-user-intent came
  down to exactly this.

- **Counterfactual effect sizes are confounded three ways.** *Non-linear
  interactions*: a factor with ~zero effect alone can produce a large drop once
  stacked with others, so single-factor effects do not add. *Incomplete
  interventions*: your change may not have actually moved the latent you targeted
  — read rollouts to confirm it landed. *Side effects*: reframing a task can
  shift the model's whole interpretation of the scenario (a "game" framing turned
  one setting into a CTF challenge).

- **Iterate on the intervention itself.** Before trusting a number, verify the
  model understood the change and that it had the intended effect. Read rollouts
  from the intervention arm, not just the aggregate rate.

- **Third-person probes: ask about the environment, not motivations.** Asking a
  model in the third person why *it* did something conflates the in-context model
  with the third-person perspective. Ask what the environment means; do not ask
  it to introspect on motive.

- **CoT is a hypothesis source, not evidence.** Never let a quote from the CoT
  carry a causal claim on its own. It generates the hypothesis; interventions
  test it.

## Claim template

Record findings in this shape so hedging survives into the deliverable:

```
CLAIM: <behavior> in <environment> is driven by <motivation>.
EVIDENCE:
  1. <prediction tested> → <result, n, rate>
  2. <independent line> → <result, n, rate>
CONTROLS: <control setting or control models, and what they showed>
BENIGN EXPLANATIONS RULED OUT: <which of the 7, and how>
CONFOUNDS REMAINING: <what could still overturn this>
CONFIDENCE: <hedged statement, not rounded up>
```

## Project integration

This repo's gates apply on top of the protocol: a forensics claim graduates only
through `falsify`, and any document carrying its numbers goes through
`validate-claims`. Record the claim as a node in `TREE.md` with evidence links —
a forensics conclusion is exactly the kind of qualitative claim that needs the
tree's discipline.
