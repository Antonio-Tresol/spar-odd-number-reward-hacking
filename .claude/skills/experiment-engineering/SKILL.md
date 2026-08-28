---
name: experiment-engineering
description: >-
  The engineering contract for research code: two modes (explore fast, promote
  when it matters) and the non-negotiable observability requirements — structured
  logging, resumable checkpoints, fail-fast ordering, error handling, and the
  pinned identity of every API call. Also covers the vendor-SDK boundary, typed
  configuration and credentials, truncation as a measurement hazard, and module
  structure for promoted code. Use whenever writing or reviewing an experiment
  script, pipeline, or any code that spends GPU time or API budget.
---

# Experiment engineering

Research code has two modes. Confusing them is what makes process feel like drag.

| | **Explore** | **Pipeline** |
|---|---|---|
| Looks like | notebook, `#%%` cells, throwaway script | `scripts/` or `src/`, CLI args, importable |
| Goal | time-to-insight | reproducibility and reuse |
| Polish (naming, structure, types) | **skip it** | apply it |
| Observability contract (below) | required as soon as a run costs real time or money | required always |
| Linting gates | not enforced | enforced |

Most work is explore mode; the workflow literature puts it around 75%. Code is
**promoted** to pipeline mode when it produces evidence a claim will rest on, when
someone else must run it, or when it will run more than a few times. Promotion is
the gate; there is no gate on exploring.

## The observability contract (non-negotiable for any run that costs time or money)

These are not polish. Polish can be deferred forever; these cannot, because
un-observable work has to be re-run, and re-running is slower than logging was.

1. **Structured results, written incrementally.** Append one JSON line per unit of
   work — metadata, inputs, outputs — to a `.jsonl` under `results/`. Analyze with
   pandas afterwards. Write as you go, not at the end: a crash at 90% must not cost
   90% of the run. These files are the evidence the research tree links to.
2. **Resumable by construction.** Before any expensive call, check whether its
   result already exists on disk; skip if so. Cache keyed by the inputs (one file
   per generation is enough; a few lines of code). The test: **kill the script
   halfway and re-run it. It should pick up where it left off, not start over.**
   Applies to API calls, generations, and long training loops (periodic checkpoints).
3. **Fail fast.** Order the script so the most likely crash happens as early as
   possible. Do not spend minutes tokenizing before the first backward pass can
   fail. Validate config, paths, credentials, and shapes up front; smoke-test on a
   tiny slice (a handful of items, the smallest model) before the full run.
4. **Error handling that preserves work.** A failure on one item must not kill the
   batch: catch per item, record the error into the results file as a row with an
   `error` field, and continue. Never swallow an exception silently, and never let
   a partial failure masquerade as a complete run; the results file must make the
   difference visible.
5. **Logging to a file, not just stdout — with an ETA.** Timestamped, config
   echoed at start, model identifier and date, seed, git commit. A terminal that
   scrolled away or an SSH session that dropped is not a record. **Every long
   loop reports progress and an ETA**, giving completed/total, rate, elapsed, and
   estimated remaining, through the *logger*, not only a progress bar: a `tqdm` bar on
   stderr is invisible in a `nohup` log, which is exactly where you need it. You
   should be able to answer "will this finish before I go home?" by tailing a file.
6. **Seeds and shuffling.** Fix and record seeds. Always shuffle datasets yourself.
   It is free, and do not rely on someone else having done it. Sample subsets
   randomly rather than taking the first *n*.
7. **Pin and record the full identity of every API call.** A recorded seed is
   nowhere near sufficient, because three things drift under an identical script.
   Model aliases get repointed at new weights: send the dated snapshot, not the
   alias. One model id is served by many providers at different quantizations:
   pin the provider, make an unavailable pin an error rather than a silent
   reroute, and refuse providers that would ignore parameters you rely on
   (on OpenRouter: `allow_fallbacks: false`, `require_parameters: true`).
   And every sampling parameter you do not send falls back to a per-provider
   default: send them all — temperature, top_p, top_k, max_tokens — and write
   them into the results file, since an unrecorded parameter cannot be compared
   across runs. Where the API can report which provider and resolved model
   actually served the call, enable that and record it, so the pin is auditable
   from the results file alone. Know what a seed buys you: on a continuously
   batched endpoint at nonzero temperature it is best-effort, so the
   reproducibility that carries evidence is distributional — n rollouts and an
   interval — not per-rollout replay.

## Calling an API at volume

Runnable reference: `references/api_runner.py` (dependency-free; adapt `call_one`).

- **Bounded concurrency, never an unbounded `gather`.** A semaphore sized to your
  rate limit. Serial calls waste hours; unbounded calls get you rate-limited or
  billed for retries of work that was going to fail anyway.
- **Exponential backoff with FULL jitter**, honouring `Retry-After` when present.
  Jitter is not a detail: without it, every worker that got a 429 retries in
  lockstep and re-triggers the limit, a thundering herd of your own making.
- **Retry only transient failures** (429, 5xx, timeouts). A 400 will fail
  identically forever; retrying it burns your attempt budget and hides the bug.
- **Cache every response to disk, keyed by a hash of the request.** This is what
  makes a run resumable and what makes the cost of a re-run zero.
- **Cap total attempts** and record permanent failures as rows with an `error`
  field. A run that quietly dropped 3% of items is worse than one that failed.

## The vendor-SDK boundary

Mishandled SDK responses produce plausible-but-wrong results files, the exact
failure mode this skill exists to prevent, and they do it without raising.

- **Vendor types stop at one module.** Convert responses into project-owned
  typed structures (dataclasses or pydantic models) at that boundary and
  nowhere else, so a vendor change breaks one file instead of every call site,
  and so real types propagate instead of `dict[str, Any]`.
- **At the boundary, read fields with direct typed attribute access.**
  `message.content`, not `getattr(message, "content", None) or ""`. The
  getattr-with-default reads as defensive and is destructive: a renamed field
  becomes an empty string, the run records hundreds of empty responses a
  grader cannot tell from refusals, and then it scores them. A renamed field
  must raise on the first call, before budget is spent; a crash is a far
  better outcome than silent corruption.
- `getattr(obj, "x", default)` is for genuinely dynamic lookup, which a typed
  SDK response never is. Same for `hasattr` probing.
- **`isinstance` rejects an unexpected shape; it never branches quietly
  between two behaviours.** Raise on the shape you did not expect.
- **Keep absent distinct from malformed.** A genuinely optional field gets an
  explicit `is None` branch; a malformed one raises. They need different
  responses, and collapsing them hides whichever one you collapsed.

## Configuration and credentials

- **Read configuration once, at startup, into one typed object built with
  pydantic-settings, and pass it down.** It reads `.env` and the real
  environment with the right precedence (environment wins, so a cloud runner
  needs no file) and validates on construction, which is fail-fast applied to
  credentials. Never `os.environ.get(...)` at the point of use, where the
  "is it missing?" check lives in a different module from the parser. Never a
  hand-rolled `.env` parser: a real one silently mangled the two lines people
  most often paste, `export KEY=value` and `KEY=value  # comment`.
- **Keys are `SecretStr`**, so a traceback or a stray `print(settings)` cannot
  leak them; reading one requires an explicit `get_secret_value()`.
- The scaffold ships a committed `.env.example` carrying names, never values.
  Keep it current: its names are the documentation a fresh clone reads.
- **A key that reaches git history is burned.** Rotate it; deleting the commit
  is not enough.

## Using a GPU without OOMing at hour three

Runnable reference: `references/gpu_batching.py` (torch imported lazily).

- **Measure peak, not final, memory.** `reset_peak_memory_stats()` then
  `max_memory_allocated()` around each phase, logged. Peak is what OOMs you, and
  it is always higher than what you observe afterwards.
- **Know allocated vs reserved.** Reserved far above allocated is *fragmentation*,
  not a leak, and logging them separately saves you from debugging the wrong thing.
- **Choose batch size against your longest sequence, not your average.** Attention
  memory grows with the *square* of sequence length; a batch size tuned on typical
  input will OOM on the tail.
- **Sort by length, longest first.** Padding waste collapses, and, the real win,
  if the run is going to OOM it does so in the first minute rather than an hour in.
- **Halve and retry on OOM** rather than dying, persisting each completed batch so
  a failure costs one batch, not the run.
- **Binary-search the max batch size once** against the worst case, then hardcode
  it with a safety margin. Re-probing every run is wasted time.
- `empty_cache()` between phases, never inside a hot loop, because it synchronises.
- **`torch.inference_mode()` over `torch.no_grad()`** for pure inference: it
  disables autograd *and* tensor version tracking, is faster, and fails loudly
  if an inference tensor later leaks into a gradient computation. Reserve
  `no_grad` for the rare case where outputs must feed autograd later.

## Tensor discipline (required in promoted code)

Runnable reference: `references/tensor_typing.py`. Checked by `TENSOR-001/002`,
reported by `./check.sh`.

**Every tensor carries its shape in its type, vectors included, since a vector is
a rank-1 tensor.** A bare `Tensor` annotation documents nothing; the shape bug
it hides usually does not raise, it just broadcasts silently and computes the
wrong number, which you then debug for an afternoon.

```python
from jaxtyping import Bool, Float
from torch import Tensor

def project(
    activations: Float[Tensor, "batch seq d_model"],
    direction: Float[Tensor, "d_model"],          # a vector is still annotated
) -> Float[Tensor, "batch seq"]:
    return einsum(activations, direction, "b s d, d -> b s")
```

- **jaxtyping on every tensor parameter, return, and non-obvious intermediate.**
  Name the axes; keep the names consistent across the project (`b` batch,
  `s` sequence, `d` d_model, `h` heads, `v` vocab, `l` layers). They are an
  interface, not decoration.
- **einops for every shape operation**: `rearrange`, `reduce`, `repeat`,
  `einsum` instead of `.view`, `.reshape`, `.permute`, `.transpose`,
  `.squeeze`, `.unsqueeze`. `rearrange(x, "b s (h d) -> b h s d", h=heads)`
  states the intent and fails loudly if it does not hold;
  `x.view(b, s, h, -1).permute(0, 2, 1, 3)` is a puzzle with an off-by-one trap.
- **Prefer explicit `repeat` over implicit broadcasting** when materializing a
  vector across batch or sequence. Implicit broadcast is where a wrong-axis bug
  hides without ever raising.
- Enable jaxtyping's runtime checking (a typechecker decorator) during
  development; the annotations then verify shapes rather than merely asserting them.

## Structure, names, and dependencies (promoted code)

Explore-mode code can be a throwaway script. Promoted code is a module, and a
pile of sibling scripts that import each other is not a module system.

- **New capability goes into the project's package** (`src/<project>/`),
  importable, with a thin CLI entry point. Reaching your own code by editing
  `sys.path` is the tell that packaging is missing; fix the structure, not the
  path. (The harness's own `scripts/` are deliberately self-contained,
  zero-install tools — that is their reason, and it is not a license for
  experiment code to accumulate there.)
- **Names say what the thing does**: modules are nouns for the thing they hold
  (`rollouts`, `grading`), functions are verbs for what they do
  (`request_completion`, `score_rollout`). A name that needs the commit
  message to decode fails review; so does a module named `utils`.
- **Types where they make the code readable**, not annotation for its own
  sake: the signatures of promoted interfaces, the settings object, tensor
  shapes, the boundary structures vendor responses convert into.
  `dict[str, Any]` flowing through a pipeline is how boundary bugs spread.
- **Prefer the canonical dependency over hand-rolling**: the official SDK for
  the API you call, tenacity for retries, pydantic for schemas,
  pydantic-settings for configuration. "Few dependencies" cuts both ways —
  hand-rolling what a maintained library already does trades tested behaviour
  for fresh bug surface (the `.env` parser above).
- **No magic numbers in experiment configuration.** Every constant that shapes
  a result — sample size, temperature, token cap, threshold — has a name, a
  home (config object or CLI argument with an explicit default), and a copy in
  the results file.

## Before you run it

Ask, in order: What is the motivation? Have I de-risked this (is there a cheaper
probe that would tell me it won't work)? What result do I expect? Am I changing too
many variables at once?

Then: **simple fast experiments on simple infra before big expensive experiments on
complex infra.** Get signal in minutes on a small model before committing GPU hours.

## After it runs, before you believe it

Look at the raw outputs, not only the metric. Plot the distribution; read actual
model responses; check the numbers are not crazy before investigating anything
programmatically. A metric computed over data you never looked at is where silent
bugs live — buggy code producing plausible-but-wrong gains is a documented failure
mode of AI-assisted research (see the harness's `research/` surveys).

**Truncation is the quiet version, and it survives a glance at the metric.** A
`max_tokens` cap that lands mid-generation returns `finish_reason: "length"`,
the row looks complete, and an answer-extraction rule happily reads a severed
digit as the model's answer — a value that is an artefact of where the cap
fell, not of anything the model decided. Two rules:

- **Check `finish_reason` before parsing, not after.** Anything other than
  `stop` is unparseable: it shrinks the reported denominator visibly instead of
  quietly biasing the rate. Analysis that reads only the response text cannot
  tell the difference.
- **Size the cap by the asymmetry.** Tokens are billed as generated, so a cap
  that is never reached costs nothing, while a cap that is reached costs a data
  point you already paid for. Err high, within the provider's ceiling, rather
  than picking a tidy round number.

## Conventions that keep runs findable

- Dated experiment folders with numbered scripts showing execution order:
  `experiments/<name>/YYMMDD_thing_v1/{1_generate.py, 2_score.py, 3_analyse.ipynb}`.
- Every script takes CLI arguments — makes it wrappable, testable, and
  parallelizable without editing code.
- Few dependencies, and none you don't understand.
- Use the fast inference path when generating at volume; naive `model.generate`
  loops are dramatically slower than dedicated inference libraries.

$ARGUMENTS
