"""Generating text at volume with vLLM — independent of activation extraction.

This is the DECODE workload, where vLLM's continuous batching and paged KV
cache earn their reputation: measured 16x over a naive HF `model.generate`
loop (2,424 stories in ~9 min vs ~2.5 h, 31B bf16, single Blackwell 96GB,
2026-07). None of the activation-extraction machinery (hooks, eager mode,
speculative config — see vllm_activation_extraction.py) is needed or wanted
here: plain generation keeps CUDA graphs and the default engine, and the two
capabilities compose only if you deliberately configure both.

Sources:
- vLLM docs (quickstart, engine args): https://docs.vllm.ai/
- Offline batched inference API (LLM.generate):
  https://docs.vllm.ai/en/latest/models/generating/ (path may drift; search
  "offline inference" in the docs)

Blackwell (SM 12.x) survival settings as of vllm 0.22 — discovered the hard
way, three failures deep:
- `VLLM_ATTENTION_BACKEND=TRITON_ATTN` (default backend fails capability
  detection: "SM 12.x requires CUDA >= 12.9"; enforce_eager does NOT fix it)
- uninstall `flashinfer-python` and set `VLLM_USE_FLASHINFER_SAMPLER=0`
  (FlashInfer JIT sampler crashes)
- build the venv on LOCAL disk, never a network volume (corrupted wheels,
  stale-file-handle errors)
"""

from __future__ import annotations

import os

os.environ.setdefault("VLLM_ATTENTION_BACKEND", "TRITON_ATTN")
os.environ.setdefault("VLLM_USE_FLASHINFER_SAMPLER", "0")


def generate_batch(
    model: str,
    user_prompts: list[str],
    max_tokens: int = 1024,
    temperature: float = 0.9,
    seed: int = 0,
) -> list[str]:
    """Chat-templated batch generation. Pass ALL prompts in one call — vLLM's
    scheduler does the batching; hand-chunking only hurts throughput."""
    from vllm import LLM, SamplingParams  # local: keep module importable without a GPU env

    llm = LLM(
        model=model,
        dtype="bfloat16",
        max_model_len=2048,  # size to your actual prompt+completion budget
        gpu_memory_utilization=0.90,
        enforce_eager=True,  # skip CUDA-graph capture when startup time
        # dominates a short job; DROP this line for long jobs — graphs pay
        # for themselves within minutes of decode
    )
    tokenizer = llm.get_tokenizer()
    formatted = [
        tokenizer.apply_chat_template(
            [{"role": "user", "content": p}], tokenize=False, add_generation_prompt=True
        )
        for p in user_prompts
    ]
    params = SamplingParams(max_tokens=max_tokens, temperature=temperature, seed=seed)
    outputs = llm.generate(formatted, params)
    return [o.outputs[0].text for o in outputs]
