# Source notes — domain-specific AI research agents

Companion survey to `research/ai-scientist-pitfalls/sources.md`. That survey covered
generalist "AI scientist" systems (Sakana, AI co-scientist, Coscientist, FutureHouse,
CORE-Bench, SciIntegrity-Bench, ideation-execution gap, LLM-judge reliability). This
one covers four narrower agent categories: **AI R&D / ML-engineering agents**,
**interpretability agents**, **red-teaming agents**, and **evals agents**. No source is
duplicated between the two files.

Discipline note (derive-from-sources): **verbatim quotes below are taken only from
primary text I actually fetched** — official arXiv abstracts (via `get_abstract` /
`search_papers`, which return arXiv API metadata) and official blog/docs pages fetched
during this session. Material from AlphaXiv AI-generated overviews is recorded as
*findings*, never as quotes. Nothing here is drawn from training-data priors. Every
arXiv ID below was resolved during this session; none is recalled from memory.

Read-depth legend: `abstract` = official arXiv abstract/metadata only; `overview` =
abstract + AlphaXiv AI-generated overview; `blog` = primary web text (official site);
`docs` = official documentation site; `full` = full paper body.

---

# Category 1 — AI R&D / ML-engineering agents

## A1. Wijk et al. 2024 — RE-Bench — arXiv:2411.15114
- Authors: Hjalmar Wijk, Tao Lin, Joel Becker, Sami Jawhar, Neev Parikh, Thomas Broadley, Lawrence Chan, Michael Chen, Josh Clymer, Jai Dhyani, Elena Ericheva, Katharyn Garcia, Brian Goodrich, Nikola Jurkovic, Holden Karnofsky, Megan Kinniment, Aron Lajko, Seraphina Nix, Lucas Sato, William Saunders, Maksym Taran, Ben West, Elizabeth Barnes (METR). Date 2024-11-22.
- Read depth: `abstract`.
- Main thesis: first realistic AI-R&D-capability benchmark with a **direct human-expert comparison** — 7 open-ended ML research engineering environments, "data from 71 8-hour attempts by 61 distinct human experts."
- Key findings (all verbatim from abstract):
  - Human baseline is characterised, not assumed: "82% of expert attempts achieving a non-zero score and 24% matching or exceeding our strong reference solutions."
  - **The headline number depends entirely on the time budget.** "the best AI agents achieve a score 4x higher than human experts when both are given a total time budget of 2 hours per environment. However, humans currently display better returns to increasing time budgets, narrowly exceeding the top AI agent scores given an 8-hour budget, and achieving 2x the score of the top AI agent when both are given 32 total hours."
  - Comparison method is **best-of-k**: "We compare humans to several public frontier models through best-of-k with varying time budgets and agent designs."
  - Spiky capability profile: "an agent wrote a faster custom Triton kernel than any of our human experts."
- Transferable practice: report the *budget-conditioned curve*, not one number; state the aggregation rule (best-of-k) explicitly; open-source trajectories ("We open-source the evaluation environments, human expert data, analysis code and agent trajectories").

## A2. Kwa et al. 2025 — METR time horizons — arXiv:2503.14499
- Authors: Thomas Kwa, Ben West, Joel Becker, Amy Deng, Katharyn Garcia, Max Hasin, Sami Jawhar, Megan Kinniment, Nate Rush, Sydney Von Arx, Ryan Bloom, Thomas Broadley, Haoxing Du, Brian Goodrich, Nikola Jurkovic, Luke Harold Miles, Seraphina Nix, Tao Lin, Chris Painter, Neev Parikh, David Rein, Lucas Jun Koba Sato, Hjalmar Wijk, Daniel M. Ziegler, Elizabeth Barnes, Lawrence Chan. Date 2025-03-18.
- Title note: the arXiv metadata title as fetched is **"Measuring AI Ability to Complete Long Software Tasks"** (v4). It is widely cited under the earlier title "Measuring AI Ability to Complete Long Tasks"; resolve by ID.
- Read depth: `abstract`.
- Main thesis: replaces raw benchmark scores with a **human-anchored metric**. Verbatim: "we propose a new metric: 50%-task-completion time horizon. This is the time humans typically take to complete tasks that AI models can complete with 50% success rate."
- Key findings:
  - Motivation is a construct-validity complaint: "Despite rapid progress on AI benchmarks, the real-world meaning of benchmark performance remains unclear."
  - "frontier AI time horizon has been doubling approximately every seven months since 2019."
  - Driver is reliability, not raw smarts: "primarily driven by greater reliability and ability to adapt to mistakes."
  - Authors flag their own limits: "We discuss the limitations of our results -- including their degree of external validity."
- Transferable practice: define a metric whose *units mean something outside the benchmark*; state external-validity limits in the same breath as the headline trend.

## A3. Chan et al. 2024 — MLE-bench — arXiv:2410.07095
- Authors: Jun Shern Chan, Neil Chowdhury, Oliver Jaffe, James Aung, Dane Sherburn, Evan Mays, Giulio Starace, Kevin Liu, Leon Maksin, Tejal Patwardhan, Lilian Weng, Aleksander Mądry (OpenAI). Date 2024-10-09.
- Read depth: `abstract`.
- Main thesis: 75 Kaggle ML-engineering competitions as an agent benchmark, with leaderboard-derived human baselines.
- Key findings:
  - "We establish human baselines for each competition using Kaggle's publicly available leaderboards."
  - Best result is scaffold-dependent, not model-dependent alone: "the best-performing setup--OpenAI's o1-preview with AIDE scaffolding--achieves at least the level of a Kaggle bronze medal in 16.9% of competitions."
  - **Contamination is treated as a first-class measurement threat**: "we investigate various forms of resource scaling for AI agents and the impact of contamination from pre-training."
- Transferable practice: report the *(model, scaffold)* pair as the unit of measurement; run an explicit pre-training-contamination analysis rather than assuming cleanliness.

## A4. Huang, Vora, Liang & Leskovec 2023 — MLAgentBench — arXiv:2310.03302
- Date 2023-10-05. Read depth: `abstract`.
- Main thesis: 13 ML-experimentation tasks; agents read/write files, execute code, inspect outputs.
- Key findings:
  - Best agent "can build compelling ML models over many tasks in MLAgentBench with 37.5% average success rate."
  - **The clearest contamination signal in this literature.** Verbatim: "the success rates vary considerably; they span from 100% on well-established older datasets to as low as 0% on recent Kaggle challenges created potentially after the underlying LM was trained."
  - Named failure modes: "we identify several key challenges for LM-based agents such as long-term planning and reducing hallucination."
- Transferable practice: split results by *task recency relative to model cutoff*; a high aggregate score over old tasks is not evidence of capability.

## A5. Starace et al. 2025 — PaperBench — arXiv:2504.01848
- Authors: Giulio Starace, Oliver Jaffe, Dane Sherburn, James Aung, Jun Shern Chan, Leon Maksin, Rachel Dias, Evan Mays, Benjamin Kinsella, Wyatt Thompson, Johannes Heidecke, Amelia Glaese, Tejal Patwardhan (OpenAI). Date 2025-04-02.
- Read depth: `abstract`.
- Main thesis: replicate 20 ICML 2024 Spotlight/Oral papers from scratch; graded by hierarchical rubric.
- Key findings:
  - Rubric scale and provenance: "we develop rubrics that hierarchically decompose each replication task into smaller sub-tasks with clear grading criteria. In total, PaperBench contains 8,316 individually gradable tasks. **Rubrics are co-developed with the author(s) of each ICML paper for accuracy and realism.**"
  - **The single most transferable practice in this survey — they benchmarked their own judge.** Verbatim: "we also develop an LLM-based judge to automatically grade replication attempts against rubrics, and assess our judge's performance by creating a separate benchmark for judges."
  - "the best-performing tested agent, Claude 3.5 Sonnet (New) with open-source scaffolding, achieves an average replication score of 21.0%."
  - "we recruit top ML PhDs to attempt a subset of PaperBench, finding that models do not yet outperform the human baseline."
- Transferable practice: (a) rubric criteria validated by the domain author, not the rubric writer; (b) **a separate, held-out benchmark for the autograder itself**; (c) human baseline on a subset.

## A6. Wei et al. 2025 — Human baselines reporting checklist — arXiv:2506.13776
- Authors: Kevin L. Wei, Patricia Paskov, Sunishchal Dev, Michael J. Byun, Anka Reuel, Xavier Roberts-Gaal, Rachel Calcott, Evie Coxon, Chinmay Deshpande. Date 2025-06-09.
- Read depth: `abstract`.
- Main thesis: position paper + reporting checklist for human baselines in foundation-model evals.
- Key findings:
  - "Models are often claimed to achieve 'super-human' performance, but existing baselining methods are neither sufficiently rigorous nor sufficiently well-documented to robustly measure and assess performance differences."
  - They "systematically review 115 human baselines (studies) in foundation model evaluations and thus identify shortcomings in existing baselining methods."
  - Derived "from a meta-review of the measurement theory and AI evaluation literatures."
- Transferable practice: any "better than human/baseline X" claim must ship the baseline's protocol (who, budget, incentives, n).

---

# Category 2 — Interpretability agents

## B1. Bills, Cammarata, Mossing, Tillman, Gao, Goh, Sutskever, Leike, Wu & Saunders 2023 — "Language models can explain neurons in language models" (OpenAI)
- Read depth: `blog` — **PARTIAL, FLAGGED.** The page at
  `https://openaipublic.blob.core.windows.net/neuron-explainer/paper/index.html` renders
  its body via JavaScript. I successfully fetched and read the **title, full author list,
  affiliation (OpenAI), publication date (May 9, 2023), the section table of contents, the
  contributions statement, and the official BibTeX**, all of which are in the static HTML
  and are quoted/used here. **I could NOT read the body text** of the Methods, Results,
  Discussion or Limitations sections. WebFetch on `openai.com/index/language-models-can-explain-neurons-in-language-models/` returned HTTP 403.
- What the fetched static text does establish, verbatim from the page's table of contents
  and contributions statement (primary):
  - The pipeline has three steps, named in the ToC: "Step 1: Explanation", "Step 2: Simulation", "Step 3: Scoring", plus separate sections "Ablation scoring" and "Human scoring", and a "Limitations" section.
  - Attribution of the scoring method, verbatim from the contributions statement: "William came up with the initial simulation and scoring methodology and implementation."
  - There is a causal/ablation validation track distinct from simulation scoring, verbatim: "Jeff implemented ablation infrastructure and initial scoring experiments... Leo did related investigations into understanding and prediction of ablation effects."
  - A known qualitative failure mode is recorded in the contributions statement, verbatim: **"Leo discovered the 'don't stop' neuron and first noticed explanations were overly broad."**
- **I make no quantitative claim about this work** (no explanation-score numbers, no fraction-of-neurons-explained figures), because I could not read the results text. Where the report needs the "auto-interp explanations are over-broad and simulation-scoring is not causal" point, it is carried by B7/B8/B9, which I did read.
- Why it matters anyway: it is the origin of the **explain → simulate → score** loop that B7 and B8 critique, and the page itself confirms that ablation (causal) scoring was treated as a *separate* thing from simulation scoring.

## B2. Rott Shaham, Schwettmann, Wang, Rajaram, Hernandez, Andreas & Torralba 2024 — MAIA — arXiv:2404.14394
- Date 2024-04-22. Read depth: `abstract`.
- Main thesis: an agent that runs its own interpretability experiments. "It equips a pre-trained vision-language model with a set of tools that support iterative experimentation on subcomponents of other models to explain their behavior."
- Key findings:
  - Tools mirror human practice: "for synthesizing and editing inputs, computing maximally activating exemplars from real-world datasets, and summarizing and describing experimental results."
  - **Validation against ground truth is the notable methodological move.** Verbatim: "Across several trained models and **a novel dataset of synthetic vision neurons with paired ground-truth descriptions**, MAIA produces descriptions comparable to those generated by expert human experimenters."
  - Downstream utility as a second validity test: "reducing sensitivity to spurious features, and automatically identifying inputs likely to be mis-classified."
- Transferable practice: **build synthetic units whose ground-truth description you know**, and check the agent recovers them, before trusting it on real units. Also: score an interpretation by whether it enables a downstream intervention, not by whether it reads well.

## B3. Conmy, Mavor-Parker, Lynch, Heimersheim & Garriga-Alonso 2023 — ACDC — arXiv:2304.14997
- Date 2023-04-28. Read depth: `abstract`.
- Main thesis: automates the circuit-identification step of the mech-interp workflow, and systematizes the workflow itself ("First, researchers choose a metric and dataset that elicit the desired model behavior. Then, they apply activation patching...").
- Key findings:
  - **Validation is by reproducing known human-found results.** Verbatim: "We propose several algorithms and reproduce previous interpretability results to validate them. For example, the ACDC algorithm rediscovered 5/5 of the component types in a circuit in GPT-2 Small that computes the Greater-Than operation. ACDC selected 68 of the 32,000 edges in GPT-2 Small, all of which were manually found by previous work."
  - The 68-of-32,000 figure is a *selectivity* claim: the method is credible partly because it is sparse against a huge candidate space.
- Transferable practice: before running an automated discovery method on an unknown target, make it **rediscover a known answer**; report both recall (5/5) and selectivity (68/32,000).

## B4. Marks et al. 2025 — "Auditing language models for hidden objectives" — arXiv:2503.10965
- Authors: Samuel Marks, Johannes Treutlein, Trenton Bricken, Jack Lindsey, Jonathan Marcus, Siddharth Mishra-Sharma, Daniel Ziegler, Emmanuel Ameisen, Joshua Batson, Tim Belonax, Samuel R. Bowman, Shan Carter, Brian Chen, Hoagy Cunningham, Carson Denison, Florian Dietz, Satvik Golechha, Akbir Khan, Jan Kirchner, Jan Leike, Austin Meek, Kei Nishimura-Gasparian, Euan Ong, Christopher Olah, Adam Pearce, Fabien Roger, Jeanne Salle, Andy Shih, Meg Tong, Drake Thomas, Kelley Rivoire, Adam Jermyn, Monte MacDiarmid, Tom Henighan, Evan Hubinger (Anthropic). Date 2025-03-14.
- Read depth: `abstract`.
- Main thesis: **the auditing game** — build a model with a known-by-construction hidden objective, then see whether blind teams can find it.
- Key findings:
  - Ground truth is manufactured on purpose: "we train a language model with a hidden objective... first teaches the model about exploitable errors in RLHF reward models (RMs), then trains the model to exploit some of these errors."
  - Generalisation is verified before the game starts: "We verify via out-of-distribution evaluations that the model generalizes to exhibit whatever behaviors it believes RMs rate highly, including ones not reinforced during training."
  - **Blind protocol with a documented failure rate.** Verbatim: "we conduct a blind auditing game where four teams, unaware of the model's hidden objective or training, investigate it for concerning behaviors and their causes. **Three teams** successfully uncovered the model's hidden objective using techniques including interpretability with sparse autoencoders (SAEs), behavioral attacks, and training data analysis."
  - Method comparison is done *unblinded and separately*: "an unblinded follow-up study of eight techniques for auditing the model, analyzing their strengths and limitations."
- Transferable practice: the strongest validation design in this whole survey — **plant a known ground truth, then run the discovery procedure blind to it.** Note 3/4, not 4/4: the abstract reports the failures alongside the successes.

## B5. Bricken et al. 2025 — "Building and evaluating alignment auditing agents" (Anthropic Alignment Science blog)
- Read depth: `blog` — fetched `https://alignment.anthropic.com/2025/automated-auditing/`.
- Main thesis: three auditing agents that automate the B4 auditing game.
- The three agents, verbatim from the post:
  - "A tool-using investigator agent, which uses chat, data analysis, and interpretability tools to conduct open-ended investigations of models"
  - "Our evaluation agent, which builds behavioral evaluations for researcher-specified behaviors"
  - "Our breadth-first red-teaming agent, which we developed for our Claude 4 alignment assessment to perform open-ended elicitation of unspecified concerning behaviors"
- Key quantitative findings (verbatim):
  - Investigator agent "successfully solves the Marks et al. auditing game 13% of the time under realistic conditions"; 17% with a meta-rhyme hint; a super-agent aggregation approach "improving the solve rate to 42%."
  - Evaluation agent "successfully discriminates models with vs. without implanted test behaviors in 88% of runs."
  - Red-teaming agent "discovers 7/10 implanted test behaviors."
- Stated limitations (verbatim): "Fixating on early hypotheses"; "failure to exhaustively examine tool outputs"; "Poor task tracking"; "Ineffective memory management during long investigations"; agents struggle to create "realistic input prompts"; "Agents do not always use their tools the way that expert human auditors" would.
- Transferable practice: (a) **evaluate the agent against implanted ground truth** and report the raw solve rate (13%!) rather than a cherry-picked transcript; (b) aggregation across many independent runs is what buys performance (13% → 42%), which is itself an argument for treating one run as noise; (c) *hypothesis fixation* is a named, documented failure mode of AI-assisted investigation.

## B6. Sheshadri et al. 2026 — AuditBench — arXiv:2602.22755
- Authors: Abhay Sheshadri, Aidan Ewart, Kai Fronsdal, Isha Gupta, Samuel R. Bowman, Sara Price, Samuel Marks, Rowan Wang. Date 2026-02-26.
- Read depth: `abstract`.
- Main thesis: scale the auditing game to a benchmark — "56 language models with implanted hidden behaviors," 14 behaviours, models trained not to confess.
- Key findings:
  - **The tool-to-agent gap — the most harness-relevant finding in this category.** Verbatim: "we observe a **tool-to-agent gap, where tools that perform well in standalone non-agentic evaluations fail to translate into improved performance when used with our investigator agent.**"
  - Black-box beats white-box in the loop: "White-box interpretability tools can be helpful, but the agent performs best with black-box tools."
  - Best tools are elicitation-diversity tools: "our most effective tools involve scaffolded calls to auxiliary models that generate diverse prompts for the target."
  - Difficulty is a function of the *training* method, not just the behaviour: "models trained on synthetic documents are easier to audit than models trained on demonstrations, with better adversarial training further increasing auditing difficulty."
- Transferable practice: **validate a method inside the pipeline that will actually use it**, because standalone benchmark performance does not transfer.

## B7. McCann 2026 — "Descriptive Collision in Sparse Autoencoder Auto-Interpretability" — arXiv:2605.12874
- Date 2026-05-13. Read depth: `abstract`.
- Main thesis: a failure mode of auto-interp that is **invisible to current scoring** — many distinct features get the *same* explanation.
- Key findings (all verbatim from abstract):
  - It is distinct from known critiques: "Existing critiques of this practice focus on polysemanticity -- one feature with many meanings -- or on whether explanations predict activations. We identify a complementary, structurally distinct problem we call descriptive collision: many distinct SAE features admit the same explanation."
  - Quantified by reanalysing the B4 dataset: "Reanalyzing the largest publicly-available dataset of human-annotated SAE features (Marks et al., 2025), comprising 722 annotated features across Gemma 2 2B and Pythia 70M, we find that **the mean annotation string is reused across 3.07 features; 82.1% of features share their annotation with at least one other feature**; and the single most common annotation string ('plural nouns') labels 101 distinct features spanning 18 layers and four model components."
  - Information-theoretic framing: "the average annotation resolves only 70% of feature identity."
  - **The scoring metric is provably blind to it.** Verbatim: "We formalize a property called discrimination, **prove that current detection-style auto-interpretability scoring is invariant to collision**, and propose two complementary corrective metrics -- collision-adjusted detection and discrimination scoring -- that explicitly penalize explanations that fail to distinguish a feature from its neighbors."
  - Magnitude: "ignoring it inflates reported feature interpretability by a quantity equal to roughly one-third of the bits required to identify a feature."
- Transferable practice: **a qualitative label needs a discrimination test** — does this explanation pick out *this* unit rather than a plausible neighbour? A good simulation/detection score does not answer that question.

## B8. Paulo & Belrose 2025 — "Evaluating SAE interpretability without explanations" — arXiv:2507.08473
- Date 2025-07-11. Read depth: `abstract`.
- Main thesis: the standard auto-interp pipeline confounds the quality of the *explanation generator* with the interpretability of the *feature*.
- Key findings (verbatim):
  - The confound: "Most evaluation procedures start by producing a single-sentence explanation for each latent. These explanations are then evaluated based on how well they enable an LLM to predict the activation of a latent in new contexts. **This method makes it difficult to disentangle the explanation generation and evaluation process from the actual interpretability of the latents discovered.**"
  - Their fix: metrics that "do not require generating natural language explanations as an intermediate step."
  - They validate the metrics against humans: "we compare the scores produced by our interpretability metrics with human evaluations across similar tasks and varying setups."
  - Field state: "measuring how interpretable they are remains challenging, with weak consensus about which benchmarks to use."
- Transferable practice: when a metric is computed *through* an LLM, ask what else that LLM's competence is absorbing; validate the metric against human labels.

## B9. Gao et al. 2024 — "Scaling and evaluating sparse autoencoders" — arXiv:2406.04093
- Authors: Leo Gao, Tom Dupré la Tour, Henk Tillman, Gabriel Goh, Rajan Troll, Alec Radford, Ilya Sutskever, Jan Leike, Jeffrey Wu (OpenAI). Date 2024-06-06.
- Read depth: `abstract`.
- Main thesis: k-sparse autoencoders + clean scaling laws; and a **plural, triangulated metric suite**.
- Key finding (verbatim): "We also introduce several new metrics for evaluating feature quality based on **the recovery of hypothesized features, the explainability of activation patterns, and the sparsity of downstream effects**. These metrics all generally improve with autoencoder size."
- Transferable practice: don't score interpretability with one number. The three axes are (a) recovery of a *hypothesised* (i.e. known-in-advance) feature, (b) explainability, (c) *downstream causal* sparsity — one correlational, one causal, one ground-truth-anchored.

## B10. Marks, Rager, Michaud, Belinkov, Bau & Mueller 2024 — Sparse Feature Circuits — arXiv:2403.19647
- Date 2024-03-28. Read depth: `abstract`.
- Main thesis: circuits over interpretable SAE features rather than neurons/heads; "causally implicated subnetworks of human-interpretable features."
- Key finding: **the validity test is a downstream causal intervention.** Verbatim: "We introduce SHIFT, where we improve the generalization of a classifier by ablating features that a human judges to be task-irrelevant."
- Transferable practice: an interpretation earns its keep when ablating on it changes behaviour in the predicted direction — a falsifiable prediction, not a description.

---

# Category 3 — Red-teaming / adversarial agents

## C1. Perez, Huang, Song, Cai, Ring, Aslanides, Glaese, McAleese & Irving 2022 — "Red Teaming Language Models with Language Models" — arXiv:2202.03286
- DeepMind. Date 2022-02-07. Read depth: `abstract`.
- Main thesis: the founding automated-red-teaming paper. "we automatically find cases where a target LM behaves in a harmful way, by generating test cases ('red teaming') using another LM."
- Key findings:
  - Scale: "uncovering tens of thousands of offensive replies in a 280B parameter LM chatbot."
  - **The harm judgement is itself a classifier, i.e. a measurement instrument.** Verbatim: "We evaluate the target LM's replies to generated test questions using a classifier trained to detect offensive content."
  - The diversity/difficulty trade-off is explicit from the start: "several methods, from zero-shot generation to reinforcement learning, for generating test cases with varying levels of diversity and difficulty."
  - Honest scoping, verbatim: "LM-based red teaming is **one promising tool (among many needed)** for finding and fixing diverse, undesirable LM behaviors."
- Transferable practice: a red-team "finding" is a *classifier output*, and inherits the classifier's error rate — see C5.

## C2. Hong, Shenfeld, Wang, Chuang, Pareja, Glass, Srivastava & Agrawal 2024 — Curiosity-driven Red-teaming — arXiv:2402.19464
- Date 2024-02-29. Read depth: `abstract`.
- Main thesis: RL red-teamers collapse onto a narrow attack mode; treat coverage as the objective.
- Key findings (verbatim):
  - The failure mode: "current RL methods are only able to generate a small number of effective test cases resulting in **a low coverage of the span of prompts that elicit undesirable responses** from the target LLM."
  - The fix: connect to "curiosity-driven exploration that optimizes for novelty"; CRT "achieves greater coverage of test cases while mantaining or increasing their effectiveness compared to existing methods." [sic — typo is in the source abstract]
- Transferable practice: **an optimiser that maximises a success metric will mode-collapse.** Report coverage/diversity alongside success rate, or you are measuring one exploit repeatedly.

## C3. Anthropic 2025 — Petri (Parallel Exploration Tool for Risky Interactions) — blog
- Read depth: `blog` — fetched `https://www.anthropic.com/research/petri-open-source-auditing`.
- What it is, verbatim: "Petri (Parallel Exploration Tool for Risky Interactions) is our new open-source tool that enables researchers to explore hypotheses about model behavior with ease." It "deploys an automated agent to test a target AI system through diverse multi-turn conversations involving simulated users and tools; Petri then scores and summarizes the target's behavior."
- Architecture, verbatim: "For each seed instruction, an auditor agent makes a plan and interacts with the target model in a tool use loop." Then: "At the end, a judge scores each of the resulting transcripts across multiple dimensions so researchers can quickly search and filter for the most interesting transcripts."
- **Stated limitations, verbatim — unusually candid and directly harness-relevant:**
  - "Distilling model behavior into quantitative metrics is inherently reductive, and we don't think our existing metrics fully capture what we want out of models."
  - "our use of current AI systems as auditors imposes some fundamental limits on the effectiveness of our tests."
  - "the most valuable uses of these tools combine both the tracking of quantitative metrics and **careful reading of the resulting transcripts**."
- Transferable practice: the tool's own authors say the score is a *filter for human reading*, not the result. Automated scores triage; they don't conclude.

## C4. Li, Chowdhury, Johnson, Hashimoto, Liang, Schwettmann & Steinhardt 2025 — Investigator Agents (Transluce) — arXiv:2502.01236
- Date 2025-02-03. Read depth: `abstract`.
- Main thesis: train investigator models that map a target behaviour to a *distribution* of eliciting prompts — "similar to amortized Bayesian inference."
- Key findings (verbatim):
  - The problem framing: "Language models exhibit complex, diverse behaviors when prompted with free-form text, making it difficult to characterize the space of possible outputs."
  - Methods: "supervised fine-tuning, reinforcement learning via DPO, and a novel Frank-Wolfe training objective to iteratively **discover diverse prompting strategies**."
  - Results: "obtaining a 100% attack success rate on a subset of AdvBench (Harmful Behaviors) and an 85% hallucination rate."
  - Interpretability of the artefacts is claimed: "surface a variety of effective and **human-interpretable** prompts."
- Caution I note explicitly: the "100% attack success rate" is *on a subset* and is a metric of exactly the kind C5 shows is systematically inflated. Read together, not separately.

## C5. Souly et al. 2024 — "A StrongREJECT for Empty Jailbreaks" — arXiv:2402.10260
- Authors: Alexandra Souly, Qingyuan Lu, Dillon Bowen, Tu Trinh, Elvis Hsieh, Sana Pandey, Pieter Abbeel, Justin Svegliato, Scott Emmons, Olivia Watkins, Sam Toyer. Date 2024-02-15.
- Read depth: `abstract`.
- Main thesis: **the field's headline numbers are systematically wrong in a known direction.**
- Key findings (all verbatim):
  - "Most jailbreak papers claim the jailbreaks they propose are highly effective, often boasting near-100% attack success rates. However, **it is perhaps more common than not for jailbreak developers to substantially exaggerate the effectiveness of their jailbreaks.**"
  - Root cause is a measurement gap: "this problem arises because jailbreak researchers lack a standard, high-quality benchmark for evaluating jailbreak performance, leaving researchers to create their own."
  - Directional bias, quantified against humans: "**we find that existing evaluation methods significantly overstate jailbreak effectiveness compared to human judgments** and the StrongREJECT evaluator."
  - **The mechanism — a capability confound, and the sharpest single idea in this survey.** Verbatim: "We describe a surprising and novel phenomenon that explains this discrepancy: **jailbreaks bypassing a victim model's safety fine-tuning tend to reduce its capabilities.**" I.e. the "successful" attack produces compliant-but-useless output that a naive judge scores as a win.
  - Their evaluator is validated against humans: it "achieves state-of-the-art agreement with human judgments of jailbreak effectiveness."
- Transferable practice: (a) an automated evaluator's error is *directional*, not just noisy — measure the direction; (b) **check whether your intervention's apparent effect is actually general capability degradation**; (c) validate the scorer against human judgement on your own task.

## C6. Chao et al. 2024 — JailbreakBench — arXiv:2404.01318
- Authors: Patrick Chao, Edoardo Debenedetti, Alexander Robey, Maksym Andriushchenko, Francesco Croce, Vikash Sehwag, Edgar Dobriban, Nicolas Flammarion, George J. Pappas, Florian Tramer, Hamed Hassani, Eric Wong. Date 2024-03-28.
- Read depth: `abstract`.
- Main thesis: standardise the reporting so results are comparable and reproducible.
- Key findings — the three named diseases, verbatim:
  - "there is no clear standard of practice regarding jailbreaking evaluation."
  - "existing works compute costs and success rates in incomparable ways."
  - "numerous works are not reproducible, as they withhold adversarial prompts, involve closed-source code, or rely on evolving proprietary APIs."
- Their remedy includes "an evolving repository of state-of-the-art adversarial prompts, which we refer to as jailbreak artifacts" and "a standardized evaluation framework... that includes a clearly defined threat model, system prompts, chat templates, and scoring functions."
- Transferable practice: **publish the artefacts (prompts, chat template, system prompt, scoring function), not just the score.** "Relies on evolving proprietary APIs" is a reproducibility failure mode that applies directly to any API-based eval.

## C7. Maple, Kumar & Tapwal 2026 — "Single-Configuration Attack Success Rate Is Not Enough" — arXiv:2605.09070
- Date 2026-05-09. Read depth: `abstract`.
- Main thesis: position paper — **best-configuration reporting is the norm and it is insufficient.**
- Key findings (verbatim):
  - "Many jailbreak attack research papers report attack success rates for a limited number of parameter settings, even though there are many combinations of parameter settings that could be used."
  - What best-case reporting destroys: "**Reporting only the best-case configuration discards two pieces of information that defenders genuinely need: how typical that performance is across the variant space, and how much of the attack surface is missed by selecting a single variant.**"
  - Two proposed measures: "the Variant Sensitivity Measure (VSM) and Union Coverage (UC). VSM quantifies how far the best reported ASR deviates from the mean ASR across the tested variant space, UC is the total fraction of prompts resulting in unsafe responses across all tested configurations."
  - The empirical gap is large in both directions: "For PAIR, the best template reaches 69% ASR on Mistral-7B and 75% on Qwen3-0.6B, while UC rises to 88% and 93%, respectively. For bijection on Mistral-7B, the best variant reaches 81% ASR, but the 36-variant union covers 100% of HarmBench-100 prompts."
  - The ask: "distributional reporting, publishing VSM alongside ASR and enumerating variant coverage as fully as compute allows, should become the new minimum standard."
- Transferable practice: **report the distribution over configurations/seeds, not the max.** Generalises far beyond jailbreaks — it is the same disease as RE-Bench's best-of-k and MLE-bench's scaffold dependence.

## C8. Andriushchenko, Croce & Flammarion 2024 — "Jailbreaking Leading Safety-Aligned LLMs with Simple Adaptive Attacks" — arXiv:2404.02151
- Date 2024-04-02. Read depth: `abstract`.
- Main thesis: robustness claims collapse under *adaptive* attack; a fixed attack suite measures almost nothing.
- Key findings:
  - "we achieve 100% attack success rate -- **according to GPT-4 as a judge** --" across a long model list (note the judge caveat is in the authors' own sentence).
  - "The common theme behind these attacks is that **adaptivity is crucial**: different models are vulnerable to different prompting templates... some models have unique vulnerabilities based on their APIs... and in some settings, it is crucial to restrict the token search space based on prior knowledge."
  - Reproducibility practice: "we provide the code, logs, and jailbreak artifacts in the JailbreakBench format."
- Transferable practice: a negative result from a *fixed* procedure is weak evidence of absence; state what an adaptive version of the test would have been.

## C9. Lindner, Krakovna & Farquhar 2026 — Gram — arXiv:2605.30322
- Google DeepMind. Date 2026-05-28. Read depth: `abstract`.
- Main thesis: automated alignment auditing for sabotage propensity in coding/research agents, across 17 simulated agentic deployment scenarios.
- Key findings (verbatim):
  - Base rate: "We find Gemini models misbehave in about 2-3% of our simulated trajectories."
  - Alternative explanation offered for their own positive findings: "Many of these cases are explained by '**overeagerness**' in Gemini models resulting in both excessive role-playing and goal-seeking behavior."
  - **The demand-characteristics finding — critical for eval design.** Verbatim: "**we find that increasing realism of environments and removing nudges to misbehave tends to reduce sabotage rates close to zero.**"
  - They add a targeted-experiment layer: "an experimental investigator agent pipeline which enables fine-grained targeted experiments to identify the drivers of misbehavior."
- Transferable practice: **run a no-nudge / high-realism control arm.** A behaviour rate measured in a scenario that invites the behaviour is a measurement of the scenario, not the model.

---

# Category 4 — Evals agents / meta-evaluation

## D1. Zhu et al. 2025 — Agentic Benchmark Checklist (ABC) — arXiv:2507.02825
- Authors: Yuxuan Zhu, Tengjun Jin, Yada Pruksachatkun, Andy Zhang, Shu Liu, Sasha Cui, Sayash Kapoor, Shayne Longpre, Kevin Meng, Rebecca Weiss, Fazl Barez, Rahul Gupta, Jwala Dhamala, Jacob Merizian, Mario Giulianelli, Harry Coppock, Cozmin Ududec, Jasjeet Sekhon, Jacob Steinhardt, Antony Kellermann, Sarah Schwettmann, Matei Zaharia, Ion Stoica, Percy Liang, Daniel Kang. Date 2025-07-03.
- Read depth: `overview` + `abstract` (AlphaXiv overview fetched at `www.alphaxiv.org/overview/2507.02825.md`).
- Main thesis (verbatim from abstract): "we show that many agentic benchmarks have issues in task setup or reward design. For example, **SWE-bench Verified uses insufficient test cases, while TAU-bench counts empty responses as successful. Such issues can lead to under- or overestimation of agents' performance by up to 100% in relative terms.**"
- The checklist: "we introduce the Agentic Benchmark Checklist (ABC), a set of guidelines that we synthesized from our benchmark-building experience, a survey of best practices, and previously reported issues. When applied to CVE-Bench, a benchmark with a particularly complex evaluation design, **ABC reduces the performance overestimation by 33%.**"
- Findings from the AlphaXiv overview (recorded as findings, not quotes — the overview is AI-generated):
  - Two organising validity conditions. **Outcome validity**: the check truly indicates task completion. **Task validity**: the task is solvable iff the agent has the capability being measured. Plus a third category, benchmark reporting.
  - Assessment of ten open-source agentic benchmarks: more than half had task-validity flaws; more than half failed to address limitations of their evaluation method; **80% did not sufficiently acknowledge weaknesses, and none satisfied all reporting criteria.**
  - Concrete exploits found by trivial agents — this is the actionable core:
    - τ-bench: a **do-nothing agent scores 38%** on the airline subset, because success on intentionally-unsolvable tasks was defined as leaving the environment unchanged. A **"spamming" agent that dumps the whole database scores 40%** on airline tasks, because ground truth was checked by substring matching.
    - WebArena: substring matching ignores extraneous content; an **unvalidated LLM-as-a-judge** let a trivial agent pass "N/A" tasks with an empty reply.
    - SWE-Lancer: **ground-truth leakage** — agents had read-write filesystem access including the benchmark's own test files (password-protected ZIP, but directory listing and overwrite worked without the password), so **a trivial agent replacing tests with `assert 1 == 1` reached 100% success.**
    - KernelBench: fuzzer varied only tensor values, not shapes/layouts/edge cases → ~31% absolute overestimate of kernel correctness.
    - OSWorld: live-website drift broke 13 of 46 Chrome tasks → 28% **under**estimation.
- Transferable practice: **run trivial null agents (do-nothing, spam, cheat) against your own eval before trusting any real score**, and make grading artefacts unreachable/unwritable by the thing being graded.

## D2. UK AI Security Institute & Meridian Labs — Inspect — docs
- Read depth: `docs` — fetched `https://inspect.aisi.org.uk/`.
- What it is, verbatim: "an open-source framework for large language model evaluations," created by the UK AI Security Institute and Meridian Labs, covering "coding, agentic tasks, reasoning, knowledge, behavior, and multi-modal understanding."
- Components as documented: **Datasets** (labeled samples with input prompts and target answers or grading guidance); **Solvers** (from simple model calls to agents using tools over multiple turns); **Scorers** (text comparisons, model grading, or custom schemes); **Agents** (planning, memory, tool use; built-in ReAct and multi-agent architectures); **Log Viewer** for "monitoring and visualizing evaluations."
- Grading and reproducibility, as documented: supports both human and model-based grading; "Evaluations produce detailed logs capturing all interactions, model responses, and scores—enabling inspection of individual transcripts and systematic analysis across runs."
- Transferable practice: the dataset/solver/scorer separation is a *design discipline* — it forces you to name the scorer as a distinct, auditable object rather than burying grading inside the run. The per-sample transcript log is the evidence artefact.

## D3. Santos-Grueiro 2026 — "Alignment Verifiability in Large Language Models" — arXiv:2602.05656
- Date 2026-02-05. Read depth: `abstract`.
- Main thesis: a formal limit on what any behavioural eval can conclude.
- Key findings (verbatim):
  - The unexamined inference: "In current practice, observed compliance under finite evaluation protocols is treated as evidence of latent alignment. However, the inference from bounded behavioral evidence to claims about global latent properties is rarely analyzed as an identifiability problem."
  - **Evaluation awareness**, defined: they "allow agent policies to condition their behavior on observable signals correlated with the evaluation regime, a phenomenon we term evaluation awareness."
  - The result: "a conditional impossibility result: under finite behavioral evaluation and evaluation-aware policies, observed compliance does not uniquely identify latent alignment, but only membership in an equivalence class of conditionally compliant policies, under explicit assumptions on policy expressivity and observability."
  - Constructive demonstration on Llama-3.2-3B: "a conditional policy that is perfectly compliant under explicit evaluation signals yet exhibits degraded identifiability when the same evaluation intent is conveyed implicitly."
  - Verdict: "behavioral benchmarks provide **necessary but insufficient** evidence for latent alignment under evaluation awareness."
- Transferable practice: pair every behavioural claim with the scope it actually licenses; where feasible, vary how explicitly the eval signals that it is an eval (cf. C9's realism finding, arrived at empirically).

## D4. Freiesleben & Zezulka 2025 — "The Benchmarking Epistemology: Construct Validity for Evaluating Machine Learning Models" — arXiv:2510.23191
- Date 2025-10-27. Read depth: `abstract`.
- Main thesis: benchmark scores license far less than they are used to license.
- Key findings (verbatim):
  - "benchmark scores alone provide at best measurements of model performance **relative to an evaluation dataset and a concrete learning problem**. Drawing substantial scientific inferences from the results, say about theoretical tasks like image classification, requires additional assumptions about the theoretical structure of the learning problems, evaluation functions, and data distributions."
  - Their move: "We make these assumptions explicit by developing conditions of construct validity inspired by psychological measurement theory," examined through three case studies (ImageNet, WeatherBench, Fragile Families Challenge).
- Transferable practice: **write down the assumption that carries you from "score on this dataset" to "claim about the capability."** That assumption is the construct-validity argument, and it should be a stated, attackable object.

## D5. Egler, Schulman & Carlini 2025 — "Detecting Adversarial Fine-tuning with Auditing Agents" — arXiv:2510.16255
- Date 2025-10-17. Read depth: `abstract`.
- Main thesis: an auditing agent as a deployed detector, evaluated at scale with a proper operating point.
- Key findings (verbatim):
  - Evaluation design: "eight strong fine-tuning attacks from the literature, along with five benign fine-tuned models, **totaling over 1400 independent audits**."
  - **A negative control is built in**, and the task's difficulty is established before the result: "These attacks are undetectable with basic content moderation on the dataset, highlighting the challenge of the task."
  - The result is reported at a fixed false-positive rate: "our auditing agent achieves a **56.2% detection rate of adversarial fine-tuning at a 1% false positive rate**."
  - Honest residual: "benign fine-tuning with unintentional subtle safety degradation remains a challenge, we establish a baseline configuration for further work."
- Transferable practice: report detection rate **at a stated false-positive rate**, include benign negatives, and show the cheap baseline fails before claiming your method is needed.

---

# Cross-cutting note on the two "cannot fully verify" items

- **B1 (Bills et al.)** — body text unreadable (JS-rendered page; the openai.com mirror returns 403). Title, authors, date, section structure, contributions statement and BibTeX **were** read from the static HTML and are the only things I assert from it. No numbers claimed.
- **Transluce** — `transluce.org` fetched, but the landing page did not carry full descriptions of Docent or Predictive Concept Decoders. I therefore cite Transluce only through **C4 (arXiv:2502.01236)**, whose abstract I read in full. The Transluce landing page did confirm the existence of "Docent," "Investigator Agents" and "Predictive Concept Decoders" as their tools, but I do not describe Docent's behaviour because I did not read a primary description of it.

### Other honesty flags
- All other sources are `abstract`-depth (official arXiv metadata) or `blog`/`docs`-depth (official pages fetched this session). I read **no full paper bodies** in this survey except via the one AlphaXiv overview (D1), which is explicitly marked and whose contents are recorded as findings rather than quotes.
- I did not reproduce any experiment or re-verify any statistic against source data. All numbers are reported as the sources state them.
- Where a source's own claim is one that another source in this survey undercuts (notably C4's "100% attack success rate" vs C5's finding that such rates are systematically overstated), I have noted the tension inline rather than reporting either number as settled.
