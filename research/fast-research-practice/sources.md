# Source notes — fast empirical research practice

Discipline note (derive-from-sources): every source below was fetched in-session
via WebFetch. Verbatim quotes are marked and come from the fetched text only.
Read depth: `fetched-summary` = the page was fetched and summarized by the fetch
tool; I did not read the raw HTML/slides myself, so quotes are as returned by
that extraction. Nothing here comes from training-data priors.

---

## F1. Chua, Hughes, Perez & Evans (2025) — "Tips On Empirical Research Slides"
- URL: https://www.lesswrong.com/posts/i3b9uQfjJjJkwZF4f/tips-on-empirical-research-slides
- Read depth: `fetched-summary`.
- Main thesis: communicating experiments is half the work; a standing slide deck
  per project is the unit of research communication.
- Key findings:
  - **Verbatim:** "Start with the most important message first. Even though you
    worked hard to try 10 different experimental setups, you don't show all of them."
  - **Verbatim:** "doing great experiments is only half the journey, they only
    matter if people understand them!"
  - Structure: summary slide (recap last meeting + current outcomes) → agenda with
    time allocations → experimental setup → backup slides → discussion/next steps.
  - Unsuccessful experiments go in backup slides, not the main line.
  - Always show full prompts alongside results; show real model outputs in backup.
  - Error bars via standard error `SE = sqrt(p(1-p)/N)`; put actual metric values
    on charts (e.g. "51.4%"); label axes with direction (higher/lower is better).
  - Chart hygiene: max 3–5 colors; bar charts preferred over heatmaps.
  - Cost: 1–2 days for the first deck, improving to half a day with practice.
- Relevance to harness: gives a concrete, checkable structure for a communication
  skill, and a norm (full prompts + error bars + real outputs) that is a
  *transparency* practice, not a polish practice.

## F2. Steinhardt — "Research as a Stochastic Decision Process"
- URL: https://cs.stanford.edu/~jsteinhardt/ResearchasaStochasticDecisionProcess.html
- Read depth: `fetched-summary`. Author/date not captured in the fetched text;
  the page is hosted on Jacob Steinhardt's Stanford page.
- Main thesis: research is a multi-round game under uncertainty; order tasks by
  information gained per unit time, not by difficulty.
- Key findings:
  - Framing: research is "a multi-round game, where in each round we take some
    action that gives us some information; the information we get is stochastic."
  - **Verbatim principle:** "Reduce uncertainty at the fastest possible rate"
  - **Verbatim pattern:** "De-risk all components (to the extent feasible), then execute"
  - Method 1 (expected time saved): prioritize tasks whose *failure* saves the
    most downstream work.
  - Method 2 (failure rate): sort by `λ = -ln(success probability) / duration`,
    highest first.
  - Core failure mode addressed: completing easy components that turn out
    irrelevant once a hard component fails.
  - Claimed effect: 2–3x efficiency gains, more with strategic de-risking.
- Relevance: this is the ideation/prioritization backbone — it says *which
  experiment to run next* and licenses cheap, hacky de-risking probes over
  polished full builds.

## F3. dnbt777 (2024-06-07) — "How to Build Extremely Quickly"
- URL: https://learnhowtolearn.org/how-to-build-extremely-quickly/
- Read depth: `fetched-summary`.
- Main thesis: "outline speedrunning" — recursive outline, then fill fast without
  quality concern, then polish LAST.
- Key findings:
  - Three stages: recursive outlining (break down until items are small) →
    speedrunning (fill each section as fast as possible, ignoring quality) →
    perfection phase (only after completion).
  - **Verbatim anti-pattern ("loading-bar" style):** "starting at the beginning of
    the document and writing sentence by sentence".
  - **Verbatim:** "I wrote like this until I was ~20. It made me hate writing."
  - **Verbatim:** "Generally, the best speedups come from improving your algorithms,
    rather than ramming your head into the task harder."
  - **Verbatim:** "Much of becoming really efficient is about getting extremely
    cracked at the fundamentals (many of which you probably mistakenly dismiss)."
  - Claimed effect: ~10x speedup over loading-bar style, with *better* quality
    because the finished skeleton clarifies design decisions.
- Relevance: the explicit license for hacky-first code, and the crucial ordering
  claim — polish is a *phase*, not a per-line obligation.

## F4. Hughes, J. & Perez, E. (2025-01-20) — "Tips and Code for Empirical Research Workflows"
- URL: https://www.lesswrong.com/posts/6P8GYb4AjtPXx6LLB/tips-and-code-for-empirical-research-workflows
- Read depth: `fetched-summary`. Includes attributed comments by Fabien Roger
  (Jan 2025), marked below.
- Main thesis: a practical workflow handbook for empirical ML research.
- Key findings — **logging / results**:
  - **Verbatim:** "outputting a `jsonl` file at the end of the experiment with all
    the metadata, inputs, and outputs is useful" — then analyze with pandas.
  - Track experiments in a database (name, tags, users, last updated, status) for
    retrospective use when writing up.
- **Resumability / caching**:
  - **Verbatim (Roger):** "Cache LLM responses! It's only a few lines of code to
    write your own caching wrapper" — one file per generation; enables killing and
    rerunning scripts without data loss.
  - Save intermediate checkpoints to monitor progress, catch bugs early, and
    recover from interruption.
- **Fast iteration / debugging**:
  - **Verbatim (Roger):** "Make the script go to the place it could crash as fast
    as possible. For example, if a script crashes on the first backward pass after
    2 minutes of tokenization, avoid always spending 2 minutes waiting"
  - **Verbatim (Roger):** "Check that your results and metrics make sense...using
    information rich plots...make sure they are not 'crazy'"
  - Plotting/printing as the primary debugging tool; `breakpoint()` often beats print.
  - **Verbatim (Roger):** "Do simple fast experiments on simple infra before doing
    big expensive experiments on complex infra" — e.g. start with a 1B model on a
    single GPU to get signal in minutes.
- **Notebooks vs scripts (the speed/rigor boundary)**:
  - De-risk mode ≈ 75% of work: notebooks, for "quick experimentation...that
    minimize time-to-insight".
  - Extended project mode: "Transitioning from notebooks to structured scripts,
    modules, or pipelines" when compute and collaboration grow.
  - Hybrid: `#%%` cell-style Python files (version-control friendly).
- **Compute efficiency**: `simple-gpu-scheduler` for multi-GPU queuing; batch APIs
  overnight; vllm over `model.generate` (HF generate called "30x slower" by Roger);
  learn `asyncio` for concurrent API calls (tens of thousands of concurrent ops vs
  thread limits).
- **Data hygiene**: **Verbatim (Roger):** "Always shuffle your dataset—it's free,
  don't rely on someone else shuffling your dataset"; sample randomly rather than
  taking first-n; sweep learning rates (Adam: 1e-5, 3e-5, 1e-4, 3e-4); "Not training
  for long enough / on enough datapoints—fine-tune on at least 1k trajectories
  before giving up"; save and look at raw fine-tuning data.
- **Code organization**: dated experiment folders
  (`./experiments/<name>/250109_technique_v1`) with numbered scripts showing
  execution order (`1_run_harmbench.sh`, `2_run_classifier.sh`,
  `3_analyse_results.ipynb`); all scripts take CLI args (e.g. `simple_parsing`) so
  they can be wrapped, tested, and parallelized across tmux panes.
- **Dependencies**: **Verbatim (Roger):** "Use as few libraries you don't understand
  as possible. I like just using torch+huggingface+tqdm+matplotlib"
- **Pre-experiment planning**: ask "What is the motivation? Have I de-risked this?
  What result do I expect? Am I changing too many variables at once?"
- **Tooling**: pre-commit (Ruff, Black, trailing-whitespace, `nbstripout`); tmux;
  remote-edit rather than sync-commit-pull cycles.
- Relevance: this is the primary source for the observability/resumability contract
  the user asked for, and it independently supports the two-mode (explore vs
  pipeline) split.

## F5. Graham, P. (2005-03) — "Writing, Briefly"
- URL: https://paulgraham.com/writing44.html
- Read depth: `fetched-summary`.
- Main thesis: writing generates thought rather than merely transmitting it.
- Key findings:
  - **Verbatim:** "Writing doesn't just communicate ideas; it generates them."
  - **Verbatim:** "expect 80% of the ideas in an essay to happen after you start
    writing it, and 50% of those you start with to be wrong."
  - Those who avoid writing "miss out on most of the ideas writing would have generated."
- Relevance: the justification for writing-as-thinking in the ideation skill and
  for the research log being a *thinking* instrument, not just a record. The "50%
  of those you start with are wrong" figure also supports cheap early de-risking
  (F2) and provisional-then-revise (F3).

---

### Cross-source synthesis

**Agreement — speed comes from ordering, not from hurrying.** F2 ("reduce
uncertainty at the fastest possible rate", de-risk then execute) and F3 (outline
recursively, speedrun, polish last) and F4 ("simple fast experiments on simple
infra before... big expensive experiments") independently converge: the win is
sequencing cheap informative work ahead of expensive work. F3's "best speedups
come from improving your algorithms, rather than ramming your head into the task
harder" is the general statement of this.

**Agreement — quality is a phase, applied selectively.** F3 makes polish an explicit
final stage; F4 splits notebooks (75%, de-risk) from scripts/pipelines (extended
projects). Neither says "write sloppy code forever" — both say *defer* polish and
*promote* code when it graduates. This is the direct answer to the 80/20 worry:
gates belong at the promotion boundary, not on exploratory code.

**Agreement — inspect raw outputs before trusting metrics.** F4 (Roger: check
results "are not 'crazy'" with rich plots; look at raw fine-tuning data) and F1
(show real model outputs and full prompts) both make looking at the actual data a
first-class step rather than an afterthought.

**Tension worth noting.** F3 says fill sections "as rapidly as possible without
concern for quality"; F4 lists specific mistakes (unshuffled data, no LR sweep,
too-few datapoints) that are *correctness* failures, not polish failures, and that
speed does not excuse. Resolution used in the harness: separate **polish** (naming,
structure, types — defer freely) from **correctness and observability** (shuffling,
seeds, logging, checkpointing — never defer, because unlogged fast work has to be
re-run, which is slower). F4's own caching advice is the proof: the fastest
iteration loop is the one you can kill and resume.

**Asymmetry the sources acknowledge.** F4's advice is written for well-resourced ML
work (multi-GPU scheduling, RunPod, batch APIs). F1 quantifies deck cost at 1–2 days,
which is a large fraction of a short sprint. Both scale down but need judgment;
F2's de-risking framing is the most scale-free of the five.

### Gaps / what I could not verify
- All five were read via the fetch tool's extraction, not raw source. Quotes are as
  that extraction returned them; I did not view the original slides (F1) or raw HTML.
- F2's author and date were not captured in the fetched text (page is hosted on
  Jacob Steinhardt's Stanford site; cited accordingly, resolve by URL).
- F4's numeric claims (30x, 10x in F3, 2–3x in F2) are the authors' own estimates;
  none is independently verified here.
