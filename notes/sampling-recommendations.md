# Vendor-recommended sampling settings, per model (read 2026-08-25)

Source notes for `Q1.H7.E2.C12`. A subagent fetched each model's Hugging Face
README (raw), its shipped `generation_config.json`, and the vendor's API docs
where the card was silent; quotes below are verbatim from those pages as
returned by the fetch, with the URL read. OpenRouter's per-model
`default_parameters` (`GET /models`) were read directly as a second source.

The project sends `temperature=1.0, top_p=1.0, top_k=0 (off), max_tokens=32768`
to every model (see `sampling.py`).

## Summary

| model | thinking-mode recommendation | shipped `generation_config.json` | OpenRouter default | differs from project on |
|---|---|---|---|---|
| Qwen/Qwen3.5-27B | T=1.0, top_p=0.95, top_k=20, min_p=0, presence_penalty=1.5 | T=0.6, top_k=20, top_p=0.95 | T=0.6, top_p=0.95, top_k=20 | top_p, top_k, presence_penalty |
| Qwen/Qwen3.6-27B | T=1.0, top_p=0.95, top_k=20, min_p=0, presence_penalty=0.0 | T=1.0, top_k=20, top_p=0.95 | unset | top_p, top_k |
| Qwen/Qwen3.8-27B | T=1.0, top_p=0.95, top_k=20, min_p=0, presence_penalty=0.0 | T=1.0, top_k=20, top_p=0.95 | T=1.0, top_p=0.95, top_k=20 | top_p, top_k |
| google/gemma-4-31B-it | T=1.0, top_p=0.95, top_k=64 (all use cases) | T=1.0, top_k=64, top_p=0.95 | T=1.0, top_p=0.95, top_k=64 | top_p, top_k |
| openai/gpt-oss-20b | T=1.0, top_p=1.0 (GitHub README; HF card has none) | no sampling fields | unset | nothing |
| deepseek-ai/DeepSeek-V4-Flash | T=1.0, top_p=1.0; API docs: thinking mode ignores temperature and top_p | T=1.0, top_p=1.0 | unset | nothing |
| zai-org/GLM-5.2 (GLM-5.3 has no public card) | API default T=1.0, top_p=0.95; evals at 1.0/0.95 (HLE) and 1.0/1.0 (agentic) | T=1.0, top_p=0.95 | T=1.0, top_p=0.95 | top_p |
| moonshotai/Kimi-K3 | T=1.0; top_p=0.95 single-step, 1.0 agentic; Moonshot's API fixes these | none | top_p=0.95 | top_p |
| MiniMaxAI/MiniMax-M3 | T=1.0, top_p=0.95 | T=1.0, top_p=0.95 | T=1.0, top_p=0.95 | top_p |

No card or doc for any of the nine says anything about greedy decoding (the
older Qwen3 "DO NOT use greedy decoding" line is absent from the 3.5/3.6/3.8
cards).

## Verbatim quotes

### Qwen/Qwen3.5-27B — https://huggingface.co/Qwen/Qwen3.5-27B

> We recommend using the following set of sampling parameters for generation
> - Thinking mode for general tasks: `temperature=1.0, top_p=0.95, top_k=20, min_p=0.0, presence_penalty=1.5, repetition_penalty=1.0`
> - Thinking mode for precise coding tasks (e.g. WebDev): `temperature=0.6, top_p=0.95, top_k=20, min_p=0.0, presence_penalty=0.0, repetition_penalty=1.0`
> - Instruct (or non-thinking) mode for general tasks: `temperature=0.7, top_p=0.8, top_k=20, min_p=0.0, presence_penalty=1.5, repetition_penalty=1.0`
> - Instruct (or non-thinking) mode for reasoning tasks: `temperature=1.0, top_p=0.95, top_k=20, min_p=0.0, presence_penalty=1.5, repetition_penalty=1.0`

> For supported frameworks, you can adjust the `presence_penalty` parameter between 0 and 2 to reduce endless repetitions. However, using a higher value may occasionally result in language mixing and a slight decrease in model performance.

> **Adequate Output Length**: We recommend using an output length of 32,768 tokens for most queries.

The card's Best Practices section gives a different fourth line
(`top_p=1.0, top_k=40, presence_penalty=2.0` for non-thinking reasoning
tasks); the card is internally inconsistent on that mode only.

### Qwen/Qwen3.6-27B — https://huggingface.co/Qwen/Qwen3.6-27B

> - Thinking mode for general tasks: `temperature=1.0, top_p=0.95, top_k=20, min_p=0.0, presence_penalty=0.0, repetition_penalty=1.0`
> - Thinking mode for precise coding tasks (e.g. WebDev): `temperature=0.6, top_p=0.95, top_k=20, min_p=0.0, presence_penalty=0.0, repetition_penalty=1.0`
> - Instruct (or non-thinking) mode: `temperature=0.7, top_p=0.80, top_k=20, min_p=0.0, presence_penalty=1.5, repetition_penalty=1.0`

### Qwen/Qwen3.8-27B — https://huggingface.co/Qwen/Qwen3.8-27B

> Qwen3.8 models operate in thinking mode by default, generating thinking content signified by `<think>\n...</think>\n\n` before producing the final response.

> - Thinking Mode: `temperature=1.0`, `top_p=0.95`, `top_k=20`, `min_p=0.0`, `presence_penalty=0.0`, `repetition_penalty=1.0`
> - Instruct (or non-thinking) mode: `temperature=0.7`, `top_p=0.80`, `top_k=20`, `min_p=0.0`, `presence_penalty=1.5`, `repetition_penalty=1.0`

### google/gemma-4-31B-it — https://huggingface.co/google/gemma-4-31B-it

> Use the following standardized sampling configuration across all use cases:
>
> * `temperature=1.0`
> * `top_p=0.95`
> * `top_k=64`

> **Trigger Thinking:** Thinking is enabled by including the `<|think|>` token at the start of the system prompt. To disable thinking, remove the token.

### openai/gpt-oss-20b — https://github.com/openai/gpt-oss (HF card has no recommendation)

> ### Recommended Sampling Parameters
>
> We recommend sampling with `temperature=1.0` and `top_p=1.0`.

### deepseek-ai/DeepSeek-V4-Flash — https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash

> For local deployment, we recommend setting the sampling parameters to `temperature = 1.0, top_p = 1.0`. For the Think Max reasoning mode, we recommend setting the context window to at least **384K** tokens.

API docs — https://api-docs.deepseek.com/guides/thinking_mode/

> Thinking mode does not support the `temperature`, `top_p`, `presence_penalty`, or `frequency_penalty` parameters.
> For compatibility with existing software, setting these parameters will not trigger an error but will also have no effect.

### GLM — https://huggingface.co/zai-org/GLM-5.2 and https://docs.z.ai/api-reference/llm/chat-completion

`https://huggingface.co/api/models/zai-org/GLM-5.3` returns 401 (no public
repo); the newest open-weights GLM on 2026-08-25 is `zai-org/GLM-5.2`. Its
card has no recommended-parameters section, only evaluation footnotes:

> * **Humanity's Last Exam (HLE) & other reasoning tasks**: We use sampling parameters of `temperature=1.0`, `top_p=0.95` for evaluation.
> * **SWE-Bench Pro**: ... Settings: `temperature=1`, `top_p=1`, `max_new_tokens=32k`, with a 400K context window.

Z.ai API reference:

> Sampling temperature, controls the randomness of the output, must be a positive number within the range: `[0.0, 1.0]`. The GLM-5.3, GLM-5.2, GLM-5.1, GLM-5, GLM-4.7, GLM-4.6 series default value is `1.0`, GLM-4.5 series default value is `0.6`, GLM-4-32B-0414-128K default value is `0.75`.
> Another method of temperature sampling, value range is: `[0.01, 1.0]`. The GLM-5.3, GLM-5.2, GLM-5.1, GLM-5, GLM-4.7, GLM-4.6, GLM-4.5 series default value is `0.95`, GLM-4-32B-0414-128K default value is `0.9`.

### moonshotai/Kimi-K3 — https://huggingface.co/moonshotai/Kimi-K3 and https://platform.kimi.ai/docs/guide/kimi-k3-quickstart

> All Kimi K3 results are obtained with reasoning effort set to 'max' and temperature = 1.0. For single-step tasks, such as GPQA Diamond, HLE-Full, and vision benchmarks without tools, we set top-p = 0.95; for agentic tasks, we set top-p = 1.0.

> Kimi K3 always has thinking enabled, and will return `reasoning_content`. Thinking effort is configured with the top-level `reasoning_effort` request field, which supports `"low"`, `"high"`, and `"max"` (default `"max"`).

Platform quickstart: `temperature=1.0`, `top_p=0.95`, `n=1`,
`presence_penalty=0`, and `frequency_penalty=0` are fixed on Moonshot's own
API. The DeepInfra endpoint used here accepts and applies the project's values.

### MiniMaxAI/MiniMax-M3 — https://huggingface.co/MiniMaxAI/MiniMax-M3

> ### Inference Parameters
>
> We recommend the following parameters for best performance: `temperature=1.0`, `top_p=0.95`.

> M3 supports three reasoning modes through the `thinking` parameter:
> - **`enabled`** — Reasoning is always enabled.
> - **`adaptive`** — M3 automatically determines when additional reasoning is beneficial.
> - **`disabled`** — Reasoning is disabled to minimize latency and maximize throughput.

## What this means for the project

Temperature 1.0 is the vendor's own thinking-mode setting for every model on
the slate. The deviation is truncation: `top_p=1.0` and `top_k` off, where
seven of nine vendors recommend `top_p=0.95` and two also recommend a `top_k`.
`Q1.H1.E4` tests whether that changes the gaming rate on qwen3.8-27b.
