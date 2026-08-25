---
name: experiment-engineering
description: >-
  The engineering contract for research code: two modes (explore fast, promote
  when it matters) and the non-negotiable observability requirements — structured
  logging, resumable checkpoints, fail-fast ordering, and error handling. Use
  whenever writing or reviewing an experiment script, pipeline, or any code that
  spends GPU time or API budget.
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

## Parallel inference with vLLM (generation at volume)

Runnable reference: `references/vllm_parallel_generation.py` (Blackwell
survival settings in its docstring).

This is the DECODE workload — the one vLLM is famous for. Measured: 16x over
a naive HF `model.generate` loop (2,424 stories in ~9 min vs ~2.5 h, 31B
bf16, single GPU). Pass all prompts in one `llm.generate` call and let the
scheduler batch; hand-chunking hurts.

**Independent of activation extraction.** Generation needs none of the
extraction machinery (no hooks, no eager mode for long jobs, no speculative
config) and vice versa — the next section's prefill-only extraction never
decodes. Configure each for its own job; they compose only if you
deliberately set up both.

Sources: [vLLM docs](https://docs.vllm.ai/) (quickstart, engine args,
offline inference).

## Extracting activations at scale (which engine)

Runnable reference: `references/vllm_activation_extraction.py` (measured
numbers and the verified vLLM config schema in its docstring).

Sources: [vLLM hidden-state extraction docs](https://docs.vllm.ai/en/latest/features/speculative_decoding/extract_hidden_states/),
[vLLM blog: extracting hidden states, 2026-03-30](https://vllm.ai/blog/2026-03-30-extract-hidden-states)
(mechanism, `>= v0.18.0`, PR #33736), [RFC: observation plugin for
activations](https://github.com/vllm-project/vllm/issues/36998) (future
first-class interp hooks), [community: vllm-hidden-states](https://github.com/agencyenterprise/vllm-hidden-states).

The engine choice depends on capture width and whether you persist, not on
generation-throughput folklore. Measured on a 31B bf16 model, 256 texts,
512-token cap (2026-07): a plain HF transformers loop with in-batch pooling
does 1,014 tok/s at 20 captured layers; vLLM-with-forward-hooks does ~3,400
tok/s at 1 layer but only 528 at 20 (blocking per-layer `.cpu()` copies —
the advantage inverts with width); vLLM's official `extract_hidden_states`
API does 977 tok/s at 20 layers *while writing the full per-token
activations to disk* (~25 GB for that batch), which the other routes don't
pay for.

- **Pooled means at any scale** → plain HF loop. Simplest; the production
  path.
- **A few layers, nothing persisted** → vLLM hooks under `enforce_eager`
  (hooks vs CUDA graphs) with the in-process engine; pool inside the hook.
- **Corpus-scale per-token dumps** → the official API (vLLM ≥ 0.18):
  prefill-only, keeps CUDA graphs, file-per-request output is naturally
  resumable. Size the dump volume first, and verify numerics against a
  reference path before first scientific use (hooks-vs-HF measured cosine
  ≥ 0.99999; the official route's outputs deserve the same check).
- **vLLM speedups are workload-specific**: the famous decode-scheduling wins
  (16x on story generation) do not transfer to prefill-only activation
  work. Benchmark on your workload shape before committing.

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
    direction: Float[Tensor, "d_model"],  # a vector is still annotated
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

## Conventions that keep runs findable

- Dated experiment folders with numbered scripts showing execution order:
  `experiments/<name>/YYMMDD_thing_v1/{1_generate.py, 2_score.py, 3_analyse.ipynb}`.
- Every script takes CLI arguments — makes it wrappable, testable, and
  parallelizable without editing code.
- Few dependencies, and none you don't understand.
- Use the fast inference path when generating at volume; naive `model.generate`
  loops are dramatically slower than dedicated inference libraries (see
  "Parallel inference with vLLM" above).

$ARGUMENTS
