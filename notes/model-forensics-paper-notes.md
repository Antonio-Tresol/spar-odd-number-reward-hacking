# Source notes — Singh et al., "Model Forensics"

Verbatim extraction notes taken 2026-08-24, per `derive-from-sources`. Every
quoted line below is copied verbatim from the source read in-session. The skill
`.claude/skills/model-forensics/` is drafted from these notes, not from the PDF
directly.

**Source:** Aditya Singh, Gerson Kroiz, Senthooran Rajamanoharan, Neel Nanda.
*Model Forensics: Investigating Whether Concerning Behavior Reflects
Misalignment.* arXiv:2606.26071, submitted 2026-06-24 (rev. 2026-06-25).
Local copy: `data/papers/2606.26071-model-forensics.pdf` (gitignored, 86 pp).

**Why this source is load-bearing:** Aditya Singh is the mentor for this SPAR
take-home. This paper defines the protocol the take-home asks us to apply.

---

## §3 Definition of motivations

> we take motivations to mean simple, easy-to-describe factors that help explain
> model behavior across a range of circumstances

> a motivation is a construct we adopt because it is useful for explaining and
> predicting behavior, not a claim about the model's internal mechanisms

Caveat recorded in the same section: models "may not always have coherent or
human-like motivations", may be "split-brained", and the intentional stance
(Dennett, 1987) is invoked explicitly.

## §4 Protocol and Methods

> We propose a simple, two-step protocol for model forensics, based on reading
> the CoT to generate hypotheses about model behavior, followed by environment
> interventions to test them. The protocol is iterative

**Step 1 — Hypothesis Generation.** Methods listed:

- *Reading the CoT* — "While not always faithful, it is a rich source of
  hypotheses that guides the collection of more rigorous evidence."
- *Sentence resampling* [Bogdan et al., 2025] — for each sentence `s_i`, resample
  k continuations from prefix `s_1..s_{i-1}` ("before") and k from `s_1..s_i`
  ("after"); the *resampling score* is the difference in target-behavior rate
  between after and before.
- *User-turn sampling* [Marks et al., 2025] — sample a user-turn continuation to
  elicit "the model's assessment of the transcript".

**Step 2 — Hypothesis Validation.** Methods listed:

- *Environment interventions* — "either test a hypothesis by checking a
  prediction it makes about the model's behavior, or run counterfactuals that
  vary a single feature of the prompt or environment".
- *Repeated resampling* [Macar et al., 2025] — generate sentence by sentence,
  rejecting and resampling any sentence in target class C, so the completed
  trace contains none; compare filtered vs baseline behavior rate.

**Standard of evidence:**

> There is no ground truth for a model forensics investigation.

> a high-quality investigation supports claims with several independent lines of
> evidence

## §7 Methodological Insights

> Predictions are the strongest evidence.

Reasoning given: the hypothesis "makes a quite precise prediction about how the
model will behave under certain conditions; such an outcome is very unlikely to
happen by random chance".

> Negative results are hard to interpret.

Three confounds named that limit what a falsified prediction proves —
**capabilities** (model fails to recognize the relevant fact), **competing
motivations** (e.g. unwilling to deceive), and **eval awareness** (aware it is a
misalignment test and subverts it). Followed by:

> To ensure our behavioral tests have sufficient recall, creating positive
> controls to validate them is a key next step.

> Counterfactuals are flexible but confounded.

Three named confounds:

1. *Non-linear interaction effects between factors* — Myanmar→Sweden has minimal
   effect at baseline but "produces a 16-point drop once other counterfactuals
   are stacked".
2. *Incomplete interventions* — "the manipulation did not fully act on the
   targeted latent".
3. *Side effects* — reframing a task as a game "shifted the model's
   interpretation toward a CTF challenge".

> Resampling focuses researcher effort.

## §8.1 Standards for rigorous investigations

> Control settings or models.

"To establish that behavior is deliberate, the investigation needs proper
controls." Where no obvious control setting exists, "one can use control models
to show the behavior is unique and surprising".

**Seven benign-explanation motifs** (verbatim headings):

1. *Task misspecification* — "the only way for it to succeed is to take a
   concerning action".
2. *Lack of judgment* — "not properly skeptical in realizing that what it is
   doing is concerning". Hardcoding example stopped when the model was "forced to
   write down after each turn whether it is running the risk of hardcoding".
3. *Overzealousness* — "beyond what the situation warrants, out of an excessive
   drive to complete the objective rather than out of misalignment".
4. *Misinterpretation of ambiguous environment features as task-relevant* —
   "When models are trained with RLVR, environment features are almost always
   task-relevant… it has a bias toward figuring out why the feature is
   task-relevant."
5. *Sycophancy* — "aware the setting is testing for a particular action, but
   rather than avoid that action, it purposefully decides to take the action".
   Called "reverse" eval awareness.
6. *Roleplaying* — "aware the scenario is fictional… not take the scenario very
   seriously since there are no real-world consequences".
7. *Incident-specific benign explanations*.

> Convergence of evidence across independent experiments.

"to lower the probability the lines of evidence share confounds, experiments
should be independent from each other".

> Reporting findings: hedged claims, absence of evidence, and red lines.

> resist the temptation to round hedged findings into clean claims

## §8.2 Practical Advice

> Read many rollouts by hand.

"The most informative intuitions… came from patterns visible only after reading
dozens of rollouts. While LLMs can help with this step, we think they currently
cannot replace the key intuition gained by reading rollouts by hand."

> Two ways of thinking about environment interventions.

> In practice, an investigation typically starts with counterfactuals to trace
> the causal graph of model behavior, then moves to predictions once a specific
> hypothesis has been formed.

> Iterate on environment interventions.

Check "if the intervention has the intended effect on the model, if the model
properly understands the change".

**Common experiment set-ups** (verbatim names):

- *Playing it out* — "see if it will take downstream actions that indicate it
  knows it is violating user intent".
- *First person/third person* — "We recommend asking only about the environment,
  rather than about motivations." (Interpretation is tricky due to the
  perspective shift.)
- *In-rollout follow-up question* — "Probe a model's understanding while
  controlling for context… but is frequently an unnatural intervention."

## Case-study results (for calibration)

- **Kimi K2 Thinking** — shortcut-taking driven by a disposition toward
  low-effort solutions (Pre-commit Hook). Prediction tested: as type errors
  decrease, workaround rate should smoothly decrease — confirmed.
- **DeepSeek R1** — deception motivated by consistency with previous outputs
  (Eval Tampering). Sentence resampling surfaced self-consistency sentences;
  repeated resampling to suppress them produced "the sharp drop in deception".
- Tests for belief in violating user intent were inconclusive **without positive
  controls**.

## Relevance to Q1 (Odd Number)

Motif 4 (misinterpretation of ambiguous environment features as task-relevant)
is the most direct competing explanation to "reward hacking" for the Odd Number
environment: an in-context reward function is exactly an ambiguous, surprising
environment feature that an RLVR-trained model is biased toward treating as
task-relevant. Motif 1 (task misspecification) is the second: the prompt
arguably makes the two instructions unsatisfiable together.
