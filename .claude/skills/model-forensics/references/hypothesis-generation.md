# Hypothesis generation beyond reading the CoT (Appendix D)

Load this when CoT reading has run dry — the traces are uninformative, the model
does not expose reasoning, or you suspect the driver is something the model never
verbalises.

The paper's framing: these sources "become more important in futures where the
CoT is less complete, faithful, or is replaced with latent CoT architectures."
That future is partly here already — several hosted reasoning models expose only
summarised or no CoT.

The nine sources, roughly ordered from most to least accessible without model
internals.

## Available with API access only

**6. Non-assistant persona sampling.** Sample continuations *outside* assistant
turns — user turns, tool-call results, pretraining-style transcripts. These can
elicit beliefs about the user and environment that the model never verbalises in
assistant turns. The cheapest thing on this list; try it before anything below.

**7. Unsupervised environment interventions.** Let an automated agent sweep every
variable plausibly relevant to the behavior — prompt wording, framing, recipient,
surrounding files, tool affordances — recording the relative change in target
behavior rate. Large-effect variables become candidate causal factors.

The paper analogises this to direct logit attribution: a broad automated sweep
that tells you *where* to look, not *why*. Treat the output as a ranked candidate
list, not as findings. Cheap to run, easy to over-read.

**8. Partial resampling.** Resample from before and after partial continuations
to learn which parts of a rollout matter — sentences in a reasoning trace, or
turns in an agentic trajectory. See `methods.md` for the procedure; listed here
because it doubles as an unsupervised generator, not only a validator.

**9. Looking at analogous RL training environments.** Review transcripts from RL
training environments resembling the one under study. The worked example: the
SAE latent patterns present when Opus 4.5 fabricates web-search results replicate
in anti-prompt-injection RL environments — which is what suggested the hypothesis
that the model was treating the situation as a prompt-injection attack.

This is the one source on the list that generates *incident-specific benign
explanations* (motif 7), so it is disproportionately useful when the goal is
ruling misalignment out rather than in.

**5. Training models to report on their own behavior.** A scalable route to
unsupervised insight; the paper cites positive evidence that free-text
explanations track the factors actually driving predictions. Requires training,
so it is out of scope for a short investigation — noted for completeness.

## Requires activations (open weights or an interpretability API)

**1. Natural language autoencoders (NLAs).** Produce holistic natural-language
descriptions of a model's residual-stream activations. The headline result for
forensics: NLAs surfaced safety-relevant phenomena the CoT did *not* — including
unverbalized evaluation awareness during the Claude Opus 4.6 pre-deployment
audit. That is precisely the failure mode CoT reading cannot cover.

**2. Activation oracles.** The supervised analogue of NLAs: a general
question-answering interface over activations. Reported as state of the art
across model-organism secret-keeping tasks, which is a strong proxy for
hypothesis generation.

**3. Sparse autoencoders.** Decompose activations into sparsely-activating,
often human-interpretable features. Active features suggest candidate hypotheses
about what the model is representing and why.

**4. Circuit tracing.** Builds an attribution graph behind a particular output —
a more granular view than SAEs, and correspondingly more effortful.

## Choosing among these

The list is ordered by access requirement, not by value. For a short,
API-only investigation the realistic set is **6, 7, 8, and 9** — and 9 is
underrated, because it is the only one that routinely produces the benign
explanation that dissolves an apparent misalignment finding.

Anything in the activations group requires open weights or special access.
Reach for them only when the behaviour is important enough to justify the setup,
and when you have specific reason to think the driver is unverbalised.
