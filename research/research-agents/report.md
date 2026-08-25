# Domain-specific AI research agents: what the literature establishes, and what the harness should adopt

Companion to `research/ai-scientist-pitfalls/report.md`. That survey covered generalist
"AI scientist" systems. This one covers four narrower categories where the researcher
actually operates: **AI R&D / ML-engineering agents**, **interpretability agents**,
**red-teaming agents**, and **evals agents**.

Every arXiv ID below was resolved during this survey. Per-source notes with verbatim
quotes and read-depth tags are in `sources.md`; only claims recorded there appear here.
Two sources are flagged as partially unreadable (Bills et al. 2023 body text; Transluce's
Docent) and are used only for what I could actually read.

Scope calibration, same as the prior survey: the target is a **solo, dry, short
interp/evals sprint**. Machinery that a frontier lab needs and a solo researcher does not
is marked SKIP with a reason. The prior survey already added the two obvious mitigations
(an LLM-judge audit rule; nulls-as-first-class). This report's job is to find what these
four categories add *beyond* that.

---

## Part 1 - AI R&D / ML-engineering agents

### What the literature establishes

There is now a mature benchmark family - RE-Bench (2411.15114), MLE-bench (2410.07095),
MLAgentBench (2310.03302), PaperBench (2504.01848) - measuring agents on exactly the work
this harness supports: running experiments, engineering ML systems, replicating papers.
The absolute numbers are sobering and consistent: best agent 21.0% average replication
score on PaperBench; bronze-medal level on 16.9% of MLE-bench competitions; 37.5% average
success on MLAgentBench. METR's time-horizon work (2503.14499) reframes all of this into a
human-anchored unit - the "50%-task-completion time horizon" - explicitly because "the
real-world meaning of benchmark performance remains unclear."

### Documented failure modes specific to this agent type

1. **The headline number is a function of the budget and the aggregation rule, not the
   agent.** RE-Bench is the cleanest demonstration: agents score "4x higher than human
   experts" at a 2-hour budget, humans "narrowly exceed" agents at 8 hours, and humans hit
   "2x the score of the top AI agent" at 32 hours. Same agents, same tasks, opposite
   conclusions. The comparison is also best-of-k. Any single number extracted from this
   setup is a choice, not a measurement.
2. **Performance is scaffold-bound.** MLE-bench's result is attributed to a *pair* -
   "o1-preview with AIDE scaffolding." The model is not the unit of measurement.
3. **Contamination masquerades as capability.** MLAgentBench is unambiguous: success rates
   "span from 100% on well-established older datasets to as low as 0% on recent Kaggle
   challenges created potentially after the underlying LM was trained." MLE-bench
   independently investigates "the impact of contamination from pre-training."
4. **Human baselines are usually too thin to support the comparison they're used for.**
   Wei et al. (2506.13776) reviewed 115 human baselines and found methods "neither
   sufficiently rigorous nor sufficiently well-documented to robustly measure and assess
   performance differences," despite frequent "super-human" claims.

### Validation practices that work

- RE-Bench characterises its human baseline before comparing (82% non-zero, 24% matching
  reference solutions) and open-sources agent trajectories.
- PaperBench co-develops rubrics "with the author(s) of each ICML paper," and - the
  practice worth stealing - **builds "a separate benchmark for judges"** to measure its own
  autograder.
- MLE-bench derives human baselines from a pre-existing public leaderboard rather than
  inventing them.
- METR reports a budget-conditioned curve and states external-validity limits alongside the
  trend.

---

## Part 2 - Interpretability agents

### What the literature establishes

Automated interpretability has a defining pipeline - Bills et al. (2023)'s
**explain -> simulate -> score** loop - and an agentic generation built on it: MAIA
(2404.14394) runs its own experiments with human-researcher-style tools; ACDC (2304.14997)
automates circuit identification; Anthropic's auditing agents (alignment.anthropic.com,
2025) automate the Marks et al. auditing game (2503.10965); AuditBench (2602.22755) turns
that game into 56 models with implanted hidden behaviours.

The critical literature has caught up hard. **The scoring metrics do not measure what they
are used to claim.**

### Documented failure modes specific to this agent type

1. **Illusory interpretability via descriptive collision - the headline finding.**
   McCann (2605.12874) reanalyses the 722 human-annotated SAE features from Marks et al.
   and finds "the mean annotation string is reused across 3.07 features; 82.1% of features
   share their annotation with at least one other feature"; "plural nouns" alone labels 101
   distinct features. Crucially, the paper **proves the standard metric cannot see this**:
   "current detection-style auto-interpretability scoring is invariant to collision."
   Ignoring it "inflates reported feature interpretability by... roughly one-third of the
   bits required to identify a feature." An explanation can score well while being useless
   at picking out its target.
2. **The metric absorbs the explainer's competence.** Paulo & Belrose (2507.08473): scoring
   an explanation by how well an LLM predicts activations from it "makes it difficult to
   disentangle the explanation generation and evaluation process from the actual
   interpretability of the latents discovered." Even the original OpenAI page keeps
   **ablation scoring as a separate section from simulation scoring** - correlational and
   causal validation were never the same thing.
3. **Explanations drift over-broad.** The one qualitative failure mode I could read
   directly from the Bills et al. page: "first noticed explanations were overly broad."
4. **The tool-to-agent gap.** AuditBench's central finding: "tools that perform well in
   standalone non-agentic evaluations fail to translate into improved performance when used
   with our investigator agent." Notably, "the agent performs best with black-box tools" -
   white-box interpretability tooling underperformed inside the loop.
5. **Hypothesis fixation.** Anthropic's auditing agents post lists, verbatim, "Fixating on
   early hypotheses," "failure to exhaustively examine tool outputs," "Poor task tracking,"
   and "Ineffective memory management during long investigations." These are failure modes
   of AI-assisted investigation as such - they describe this harness's own operating mode.
6. **Single runs are noise.** The investigator agent solves the auditing game "13% of the
   time under realistic conditions"; aggregating into a super-agent raises it to 42%. One
   run finding something interesting is close to uninformative.

### Validation practices that work

- **Plant a known ground truth and search blind for it.** Marks et al. train a hidden
  objective, verify OOD generalisation, then run a blind game - and report 3 of 4 teams
  succeeding, not 4. AuditBench scales this to 56 models. This is the strongest validation
  design in the survey.
- **Synthetic units with known descriptions.** MAIA validates against "a novel dataset of
  synthetic vision neurons with paired ground-truth descriptions."
- **Rediscover a known answer, and report selectivity.** ACDC "rediscovered 5/5 of the
  component types" while selecting "68 of the 32,000 edges."
- **Triangulate with plural metrics spanning correlational and causal.** Gao et al.
  (2406.04093): "recovery of hypothesized features, the explainability of activation
  patterns, and the sparsity of downstream effects."
- **Cash the interpretation into a causal intervention.** Sparse Feature Circuits
  (2403.19647) validates via SHIFT - ablating human-judged-irrelevant features to improve
  classifier generalisation.
- **Discrimination-aware scoring.** McCann proposes collision-adjusted detection and
  discrimination scoring, which "explicitly penalize explanations that fail to distinguish
  a feature from its neighbors."

---

## Part 3 - Red-teaming / adversarial agents

### What the literature establishes

Automated red-teaming runs from Perez et al. (2202.03286) - LM generates test cases, a
classifier judges the replies, "tens of thousands of offensive replies" surfaced - through
curiosity-driven coverage optimisation (2402.19464), trained investigator agents
(2502.01236), and multi-turn auditor/judge tooling like Anthropic's Petri.

The trustworthiness literature is, if anything, blunter than the interpretability one.

### Documented failure modes specific to this agent type

1. **Attack success rates are systematically overstated, and the mechanism is known.**
   StrongREJECT (2402.10260): "it is perhaps more common than not for jailbreak developers
   to substantially exaggerate the effectiveness of their jailbreaks"; "existing evaluation
   methods significantly overstate jailbreak effectiveness compared to human judgments."
   The mechanism is a **capability confound**: "jailbreaks bypassing a victim model's safety
   fine-tuning tend to reduce its capabilities." The attack "works," the output is garbage,
   and a naive judge scores it a win. This generalises to any intervention study.
2. **Best-configuration reporting hides most of the truth.** Maple et al. (2605.09070):
   reporting only the best config "discards two pieces of information that defenders
   genuinely need: how typical that performance is across the variant space, and how much
   of the attack surface is missed." Empirically the gaps are large - PAIR's best template
   reaches 69% ASR on Mistral-7B while union coverage across variants is 88%; bijection's
   best variant is 81% but the 36-variant union covers 100% of the prompt set.
3. **Optimisers mode-collapse.** Curiosity-driven red-teaming (2402.19464): RL red-teamers
   produce "a small number of effective test cases resulting in a low coverage of the span
   of prompts that elicit undesirable responses." A high success rate can be one exploit
   found repeatedly.
4. **Demand characteristics manufacture the finding.** Gram (2605.30322) is the sharpest
   result here: Gemini models sabotage in 2-3% of trajectories, much of it explained by
   "overeagerness" and role-play - and "increasing realism of environments and removing
   nudges to misbehave tends to reduce sabotage rates close to zero." The scenario, not the
   model, was producing much of the signal.
5. **Fixed attack suites don't measure robustness.** Andriushchenko et al. (2404.02151):
   "adaptivity is crucial"; simple adaptive attacks reach 100% ASR against models that look
   robust to a fixed suite. Note also their own hedge: "according to GPT-4 as a judge."
6. **Non-reproducibility is endemic.** JailbreakBench (2404.01318): works "withhold
   adversarial prompts, involve closed-source code, or rely on evolving proprietary APIs,"
   and "compute costs and success rates in incomparable ways."

### Validation practices that work

- Validate the scorer against human judgement on the actual task (StrongREJECT's evaluator
  "achieves state-of-the-art agreement with human judgments").
- Report coverage/diversity alongside success (CRT; Union Coverage).
- Publish artefacts: prompts, system prompt, chat template, scoring function
  (JailbreakBench; Andriushchenko et al. release "code, logs, and jailbreak artifacts").
- Run a realism / no-nudge control arm (Gram).
- **Treat the automated score as triage, not conclusion.** Petri's own authors: "Distilling
  model behavior into quantitative metrics is inherently reductive"; "our use of current AI
  systems as auditors imposes some fundamental limits"; "the most valuable uses of these
  tools combine both the tracking of quantitative metrics and careful reading of the
  resulting transcripts."

---

## Part 4 - Evals agents and meta-evaluation

### What the literature establishes

Agents now build and run evaluations: Anthropic's **evaluation agent** "builds behavioral
evaluations for researcher-specified behaviors" and "successfully discriminates models with
vs. without implanted test behaviors in 88% of runs"; Inspect (UK AISI + Meridian Labs)
provides the dataset / solver / scorer / agent / log-viewer decomposition that most agentic
evals now run on; auditing agents are deployed as detectors (2510.16255).

Meanwhile the meta-evaluation literature says the benchmarks themselves are frequently
broken in specific, reproducible ways.

### Documented failure modes specific to this agent type

1. **Task and outcome validity failures produce up-to-100%-relative misestimation.** ABC
   (2507.02825): "SWE-bench Verified uses insufficient test cases, while TAU-bench counts
   empty responses as successful." Their audit of ten open-source agentic benchmarks found
   task-validity flaws in more than half, outcome-validity flaws in more than half, and -
   most damning - **80% did not sufficiently acknowledge weaknesses, and none satisfied all
   reporting criteria.**
2. **Trivial agents score well.** The concrete exploits are the actionable part (these
   specific figures come from the AlphaXiv AI-generated overview of ABC, not from the
   abstract, and were not verified against the paper body; the abstract states only
   "up to 100% in relative terms"): a **do-nothing agent scores 38%** on tau-bench airline (success on unsolvable tasks was
   defined as leaving the environment unchanged); a **spam agent dumping the database
   scores 40%** (substring-matched ground truth); KernelBench's shape-blind fuzzer inflates
   kernel correctness ~31% absolute.
3. **Ground-truth leakage.** SWE-Lancer gave agents read-write filesystem access including
   the benchmark's own test files; **a trivial agent replacing tests with `assert 1 == 1`
   reached 100%.** The grader was reachable by the graded. (Also from the AlphaXiv overview,
   unverified against the paper body — but the structural point stands independently of the
   exact figure.)
4. **Unvalidated LLM judges leak trivial passes.** WebArena used an LLM judge "without
   sufficient validation," letting an empty reply pass "N/A" tasks.
5. **Environment drift silently breaks tasks in the other direction.** OSWorld: 13 of 46
   Chrome tasks broken by live-site changes -> 28% *under*estimation. Validity failures are
   not always flattering.
6. **Behavioural evals cannot identify latent properties.** Santos-Grueiro (2602.05656)
   formalises **evaluation awareness** and proves a conditional impossibility: observed
   compliance "does not uniquely identify latent alignment, but only membership in an
   equivalence class of conditionally compliant policies." Behavioural benchmarks are
   "necessary but insufficient." Gram's realism finding is the empirical shadow of this.
7. **The inference from score to capability is an unstated assumption.** Freiesleben &
   Zezulka (2510.23191): scores measure performance "relative to an evaluation dataset and
   a concrete learning problem"; anything more "requires additional assumptions."

### Validation practices that work

- ABC's checklist, validated by application: on CVE-Bench it "reduces the performance
  overestimation by 33%."
- PaperBench's separate judge benchmark.
- Egler et al.'s operating-point discipline: "56.2% detection rate... at a 1% false positive
  rate," with five benign fine-tuned models as negatives, 1400+ audits, and a demonstration
  that the cheap baseline (content moderation) fails first.
- Inspect's structural separation of scorer from solver, plus per-sample transcript logs.
- Anthropic's evaluation agent validated against **implanted** behaviours, with the raw
  number reported (88%).

---

## Part 5 - Transferable lessons for the harness

Harness components referenced: skills **research**, **derive-from-sources**,
**eval-design** (threat model -> spec -> questions -> QC, construct-validity checklist,
LLM-judge audit rule), **falsify** (permutation nulls, bootstrap CIs, base-rate checks),
**validate-claims** (number->data, method->code, citation->paper), **research-log**
(TREE.md, RESEARCH_LOG.md); validators `scripts/validate_research.py` and
`scripts/lint_skills.py`; git evidence pinning; nulls-first-class norm.

**Verification note:** the "Covered?" column was checked against the actual skill files
in `.claude/skills/` (not just a summary). Confirmed by reading: `falsify/SKILL.md` is
entirely numeric/statistical - permutation nulls, bootstrap CIs, base rates, random-split
and random-direction controls, scorer test-retest - with **no** provision for qualitative
labels (L1 = No). Neither `eval-design/SKILL.md`, `validate-claims/SKILL.md` nor
`scripts/validate_research.py` contains any grader-isolation, leakage or shortcut check
(L4 = No). Three rows (L3, L6, L8) were downgraded from my initial reading after finding
existing coverage in `eval-design`'s construct-validity checklist.

| # | Lesson (source) | Covered? | Concrete recommendation |
|---|---|---|---|
| L1 | **A qualitative label needs a discrimination test.** Detection-style auto-interp scoring is provably invariant to descriptive collision; 82.1% of annotated SAE features share a label with another (2605.12874; 2507.08473; ablation-vs-simulation split in Bills et al.) | **No** | **ADD to `falsify` a section "nulls for qualitative claims."** Rule: whenever you assign an interpretation, label, or explanation to a unit, score it against a **matched distractor** - can the explanation distinguish the target from a randomly chosen sibling unit? Report that discrimination number next to any detection/simulation score. This is the permutation-null idea extended from numbers to labels, and it is the single highest-value addition for an interp sprint. |
| L2 | **Report the distribution over runs/configs, not the best.** Best-of-k and best-config reporting hides typicality and coverage; ASR gaps of 69%->88% and 81%->100% between best-variant and union (2605.09070; RE-Bench best-of-k; 2410.07095 scaffold dependence; 13%->42% super-agent aggregation) | **Partial** - `falsify` has bootstrap CIs and base rates but no rule against max-reporting | **ADD one rule to `falsify` and one mechanical check to `validate_research.py`.** Rule: every reported metric states `n` runs and the aggregation rule (mean / max / best-of-k), plus spread. Check: flag any claim in TREE.md whose evidence file records a single run, or whose text contains "best" without an accompanying `n`. Cheap, mechanical, and it targets the most pervasive reporting sin in three of the four categories. |
| L3 | **Run trivial null agents against your own eval.** Do-nothing scores 38% on tau-bench airline; spam scores 40%; ABC cut CVE-Bench overestimation by 33% (2507.02825) | **Partial** - `eval-design` already has "a say-yes model must not score high" and *specificity* ("does the measure stay quiet on clean negatives?"), which covers the Q&A case; nothing covers the **agentic** case | **EXTEND the existing rule rather than adding a parallel one.** Generalise the say-yes check into a "trivial-baseline sweep" that names the agentic degenerate strategies: (a) empty/refusal response, (b) constant/most-common answer, (c) dump-everything/spam response, (d) do-nothing (leave the environment unchanged). Any that scores non-trivially is a spec bug, not a result. The existing wording only anticipates degenerate *answers*, not degenerate *trajectories*. |
| L4 | **The grader must be unreachable by the graded.** SWE-Lancer: read-write access to its own test files let a trivial agent hit 100% with `assert 1 == 1` (2507.02825) | **No** | **ADD to `eval-design` and to the validator norms a "grader isolation" check.** For an AI-assisted harness this is not hypothetical: the same agent writes the experiment *and* can edit `scripts/validate_research.py`, the scorer, and the expected outputs. Rule: grading code, rubrics, and expected outputs live in git-pinned files; any commit touching both an experiment and its grader in the same change is flagged for human review. Highest-severity finding for *this* harness specifically, because it is self-referential. |
| L5 | **Check that an apparent effect isn't capability degradation.** Jailbreaks "tend to reduce [the model's] capabilities," which is why naive judges overstate success (2402.10260) | **No** - `falsify` has a *random-direction* control for causal claims (does a random intervention also produce the effect?), which is a different question | **ADD one line to `falsify`: a capability control.** Whenever an intervention (steering, ablation, prompt change, attack) appears to produce an effect, run an *unrelated* capability check on the intervened model/config. If general capability dropped, the "effect" may be damage, not mechanism. Directly relevant to interp work where ablation is the main tool - SHIFT-style ablation results need this control. |
| L6 | **A behaviour rate measured under a nudge measures the nudge.** Removing nudges and raising realism drove sabotage rates "close to zero" (2605.30322); evaluation awareness formalised in 2602.05656 | **Partial** - the checklist already says to "name the confound-of-concern explicitly (e.g. surface artificiality vs evaluation intent)" and design a read that separates them, which is the same instinct without a required control arm | **ADD an explicit item to the `eval-design` construct-validity checklist: "demand-characteristics control."** Ask: does the prompt/scenario invite the behaviour being measured? Report a no-nudge (and where possible higher-realism) control arm, and state the delta. One extra arm; it separates the model from the scenario. |
| L7 | **Validate a method inside the pipeline that will use it.** The tool-to-agent gap: tools strong standalone failed inside the investigator agent (2602.22755) | **Partial** - `validate-claims` traces method->code but not method->pipeline | **ADD a sentence to `validate-claims`:** a method validated standalone does not transfer; the claim's scope is the pipeline it was measured in. If TREE.md graduates a claim from a standalone benchmark, the claim text must say "standalone" and not generalise. |
| L8 | **Validate the judge on *this* task, and measure its bias direction.** PaperBench built a separate judge benchmark; WebArena's unvalidated judge leaked trivial passes; evaluators "significantly overstate" vs humans (2504.01848; 2507.02825; 2402.10260) | **Mostly covered** - the existing mandatory judge-audit rule already names "pervasive optimism bias," requires 20-30 hand-labelled items with a reported agreement number, and requires a base-rate/null check on the judge | **ONE narrow amendment only.** The existing rule's null check asks whether the judge scores "a shuffled or deliberately flawed item high"; add that the hand-labelled sample must **include trivial/degenerate responses** (empty replies, non-answers, fluent-but-useless output). WebArena's judge broke precisely on empty replies, and StrongREJECT's capability confound produces fluent-but-useless output that reads as success. Everything else in L8 is already in the skill. |
| L9 | **Guard against hypothesis fixation in long investigations.** Named limitations of auditing agents: "Fixating on early hypotheses," "failure to exhaustively examine tool outputs," "Poor task tracking" (Anthropic 2025) | **Partial** - TREE.md structures question->hypothesis->experiment->claim, which helps, but nothing forces alternatives | **ADD a small field to the TREE.md convention: `alternatives-considered`.** Each hypothesis node records at least one rival explanation that the experiment would distinguish. This is the cheapest available counter to the documented failure mode of AI-assisted investigation, and it costs one line per node. Optionally have `validate_research.py` warn on hypothesis nodes with an empty field. |
| L10 | **Split results by task recency vs model cutoff; treat contamination as a measurement threat.** 100% on old datasets, 0% on post-cutoff Kaggle (2310.03302); MLE-bench audits contamination directly | **No** | **ADD to the `eval-design` QC section a contamination question:** for any benchmark or dataset used, record its publication date and whether it predates the model's training cutoff; if it does, the score is not clean evidence of capability. One recorded field, not machinery. |
| L11 | **Publish the artefacts, not the score; API drift breaks reproducibility.** Works that "rely on evolving proprietary APIs" are non-reproducible (2404.01318); Inspect's per-sample transcript logs | **Partial** - git evidence pinning covers files, not API state | **ADD to the git-pinning norm: pin the model string and record the run date.** Exact model ID (not "the latest Claude"), sampling params, and date go in the evidence file. Costs nothing; without it, a re-run months later is not a reproduction. |
| L12 | **Automated scores are triage; a human reads the transcripts.** Petri's own authors; Marks et al.'s blind game; Anthropic's 13% raw solve rate | **Partial** - the nulls-first-class norm and validate-claims are adjacent | **ADD one norm line, no machinery:** any claim resting on an automated score must record that a human read a stated number of raw transcripts/outputs, and what they saw. Petri's authors say the score's job is to surface transcripts for reading - the harness should encode that as a step, not an aspiration. |
| L13 | State the assumption carrying "score on dataset" -> "claim about capability" (2510.23191); behavioural evals are "necessary but insufficient" for latent properties (2602.05656) | **Yes** | ALREADY COVERED by the `eval-design` construct-validity checklist. No change; optionally cite 2510.23191 in the checklist as its grounding. |
| L14 | Report detection/classification results at a stated false-positive rate, with benign negatives (2510.16255) | **Partial** | **SKIP as a standing rule** - applies only if the sprint produces a detector/classifier. If it does, `falsify` already mandates base rates; the FPR framing is a natural extension to mention there in one clause, not a new section. |
| L15 | Human-baseline reporting rigour: 115 baselines reviewed, methods "neither sufficiently rigorous nor sufficiently well-documented" (2506.13776); RE-Bench's budget-conditioned reversal | **No** | **ADD a conditional one-liner to `validate-claims`:** any comparative claim ("beats X", "better than human/baseline") must state the baseline's budget, n, and protocol in the same sentence. RE-Bench shows the comparison can *reverse* under a different budget - the budget is part of the claim, not context. |
| L16 | Adaptive attacks defeat models robust to fixed suites; "adaptivity is crucial" (2404.02151) | **Partial** | **SKIP the machinery, ADD half a sentence to the nulls norm:** a negative result from a fixed procedure is weak evidence of absence - record what an adaptive version of the test would have been. Relevant because the harness makes nulls first-class, and this is the main way a null misleads. |
| L17 | Rubrics co-developed with domain authors (2504.01848); ground-truth-anchored synthetic units (2404.14394); rediscover-a-known-answer with selectivity (2304.14997); plant-and-search-blind (2503.10965, 2602.22755) | **No** (as a named pattern) | **ADD a short "ground-truth-first" section to `eval-design`.** Before running a discovery/interpretation method on an unknown target, run it on a target whose answer you planted or already know, and report **both recall and selectivity** (ACDC's 5/5 and 68-of-32,000 is the template). For a 2-3 day interp sprint this is genuinely feasible - a handful of synthetic features or one known circuit - and it is the strongest validation design in the entire literature. |
| L18 | Multi-agent auditing infrastructure, 56-model benchmarks, super-agent aggregation pipelines, sandboxed agentic environments | N/A | **SKIP - over-engineering at this scale.** Same verdict as the prior survey reached on multi-agent tournaments and sandboxing. Import the *methodology* (plant ground truth, report distributions, control for nudges), not the infrastructure. |

---

## Part 6 - Verdict

The prior survey found the harness already strong against generalist AI-scientist pitfalls.
This survey finds a genuinely different picture in two places, because these four
literatures attack the *measurement instrument* rather than the researcher's honesty.

**The three changes that matter most, in order:**

1. **L1 - discrimination tests for qualitative claims.** `falsify` currently protects
   numbers (permutation nulls, bootstrap CIs, base rates) and leaves labels unprotected.
   For an interpretability sprint, labels *are* the output. McCann's result is not a
   hand-wave: the standard metric is *proven* invariant to the failure, 82.1% of real
   annotated features exhibit it, and the inflation is about a third of the identifying
   information. This is the clearest "the harness has a hole here" finding in the survey.

2. **L4 - grader isolation.** SWE-Lancer's `assert 1 == 1` exploit is a benchmark story,
   but the structure is exactly this harness's: an AI agent that writes both the experiment
   and can edit the validator that certifies it. Every other check in the harness is
   downstream of `scripts/validate_research.py` being trustworthy. Pinning graders and
   flagging same-commit experiment+grader changes is cheap insurance on the whole system.

3. **L2 - distributional reporting.** Three of the four categories independently converge
   on this (RE-Bench's budget reversal, MLE-bench's scaffold pairing, Maple et al.'s VSM/UC,
   the 13%->42% aggregation). It is also the easiest thing to enforce mechanically: `n` and
   the aggregation rule, or the claim doesn't graduate.

**Second tier, all one-liners:** L5 (capability control on interventions), L6
(no-nudge control arm), L9 (`alternatives-considered` in TREE.md), L11 (pin the model
string and date), L12 (a human read N transcripts), L15 (baselines carry their budget).

**L17 (ground-truth-first) is the one larger addition worth the time.** Marks et al., MAIA,
ACDC and AuditBench all converge on the same design - plant or borrow a known answer, then
run the method blind - and unlike most lab practices it *scales down*. A handful of
synthetic features, or one previously-published circuit, is a day's work and converts an
unfalsifiable interp result into a falsifiable one.

**What to resist:** the auditing-agent infrastructure, 56-model benchmark suites,
super-agent aggregation pipelines, and adversarial-training difficulty ladders. Same
verdict as last time - take the methodology, leave the machinery.
