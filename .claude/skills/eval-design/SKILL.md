---
name: eval-design
description: Methodology for designing and building a scientifically sound LLM evaluation — threat model, specification, question design, LLM-scaled generation, quality control, and running with Inspect — with a construct-validity checklist. Use when designing an eval, writing eval questions, or assessing whether an existing eval measures what it claims.
---

# Eval design — the science of evals

Distilled from ARENA 3.0 `chapter3_llm_evals` (3.1 intro/threat-modeling, 3.2
dataset generation, 3.3 Inspect; see CLAUDE.local.md for the path of any local copy —
read the source when depth is needed). Method basis: Perez et al. 2022
(arXiv 2212.09251), Apollo Research's "A starter guide for evals" and
"We need a Science of Evals". The convergent/specificity/discriminant validity
reads below come from convergent-validity methodology (see CLAUDE.local.md for related
prior work applying it).

## The pipeline (in order; stages iterate on each other)

1. **Threat model first.** A realistic causal story by which the capability or
   tendency leads to real-world harm. Concretize as a causal graph with explicit
   assumptions and thresholds (what level of the property maps to what level of
   threat). Without this you can build a valid measurement of an irrelevant property.
2. **Specification.** Precise definition of the property (decompose into
   subproperties if needed), then one or more **operational definitions** —
   concrete measurable experiments. Use several to avoid mono-metric bias. State
   exactly what you count.
3. **Question design.** Realistic user prompts; for MCQs each item carries
   `question`, `answers`, `answer_matching_behavior`, `answer_not_matching_behavior`,
   `category`. Test each item with AND without choices shown. Apply the validity
   checklist below to every item.
4. **Scale with LLM generation.** Few-shot from seed questions + a description of
   what makes a good question + randomly-sampled variance prompts for diversity.
5. **Quality control.** LLM judge scores each item against an **anchored rubric**
   (0–10 with anchored endpoints and few-shot scored examples, including
   deliberately flawed ones); filter below threshold; then dataset-level checks:
   yes-bias, category balance, fixed choice count (so the random baseline is defined).
6. **Run with Inspect** (UK AISI `inspect_ai`): dataset → solver chain → scorer →
   `eval()`. Run the **capability baseline task before the alignment task**.

## Construct-validity checklist (apply to every question and to the eval as a whole)

The recurring sanity check: *"Is this still measuring what I wanted to measure?"*
Three distinct ways to fail: (1) the property is badly defined; (2) the property is
fine but the question is badly designed; (3) the question measures the property but
the property no longer connects to the harm — which is why the threat model exists.

Per-question:
- [ ] Does the model understand the question? (check free-form answers)
- [ ] Are free-form answers consistent with the forced-choice answer? (if not, the
      options are distorting the measurement)
- [ ] **Confounds**: is there any reason other than the target property to pick the
      matching answer? No forced trade-offs (immorality, lying, less oversight)
      that co-vary with the target. The non-matching answer must ALSO be a good,
      plausible answer — otherwise you measure competence, not tendency.
- [ ] **Revealed, not stated, preference**: embed the property in a realistic task;
      never ask "do you like X?"
- [ ] Still traceable to the specification and threat model?

Eval-level:
- [ ] **Capability floor**: can the model recognise the target behaviour at all?
      Run the capability eval before interpreting the alignment eval.
- [ ] **Position bias**: shuffle answer order (and the target) at load time.
- [ ] **Yes-bias / category-bias**: does `answer_matching_behavior` skew to one
      option or one category? A say-yes model must not score high.
- [ ] **Judge audit (mandatory if any scoring step uses an LLM-as-judge)**: LLM
      judges show pervasive optimism bias and miss discrepancies between reported
      results and actual data. Hand-label 20–30 items yourself, report judge–human
      agreement alongside every judge-derived number, and run at least one
      base-rate/null check on the judge (e.g. does it score a shuffled or
      deliberately flawed item high?). A judge-derived metric without an agreement
      number is an unvalidated claim.
- [ ] **Validity reads beyond accuracy**: *convergent* (do independent measures of the construct agree?), *specificity*
      (does the measure stay quiet on clean negatives?), *discriminant* (does it
      come apart from the confound where the confound and the construct diverge?).
      Name the confound-of-concern explicitly (e.g. surface artificiality vs
      evaluation intent) and design at least one read that separates them.

## Reusable code (copy, don't rewrite)

In the ARENA 3.0 `chapter3_llm_evals/exercises/` directory (see CLAUDE.local.md for the
local copy's path; also on GitHub under `callummcdougall/ARENA_3.0`):

- `part2_dataset_generation/solutions.py` — `generate_structured_response(s_with_threadpool)`
  (Pydantic structured output + concurrency; the most reusable pair), Pydantic
  models `Question`/`QCQuestion`, `GenPrompts` + few-shot + variance-prompt
  builders, `generate_and_score_questions` / `filter_dataset` QC loop.
- `part2_dataset_generation/power_seeking_example/` — `rubric.py` +
  `rubric_test_questions.json`: ready template for an anchored judge rubric.
- `part3_running_evals_with_inspect/solutions.py` — `record_to_sample_shuffle`
  (write your own shuffler; Inspect's built-in partially unshuffles the log),
  custom solvers/scorers, and the `benchmark_eval` vs `alignment_eval` task pair.
- Generation via OpenAI client with `base_url="https://openrouter.ai/api/v1"`.

$ARGUMENTS
