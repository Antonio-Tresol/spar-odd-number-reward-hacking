"""Extracting residual-stream activations with vLLM — two measured routes.

Benchmark context (RTX PRO 6000 Blackwell 96GB, 31B bf16 model, 256 texts
at a 512-token cap, 20 layers, 2026-07):

    HF transformers loop, batch 4, pooled in-batch . 1,014 tok/s (no dump)
    vLLM + forward hooks (eager), 1 layer .......... ~3,400 tok/s (no dump)
    vLLM + forward hooks (eager), 20 layers ........   528 tok/s (no dump)
    vLLM extract_hidden_states (official) ..........   977 tok/s + full
        per-token safetensors dump (~25 GB for the batch)

Decision rule:
  - Pooled per-text means at any scale -> plain HF loop. Simplest, and the
    blocking .cpu() copies are cheap when you pool per batch.
  - One to three layers, nothing persisted -> Route A (hooks). The per-layer
    copy cost is what kills it at width; it inverts from 2-3x faster to 2x
    slower between 1 and 20 layers.
  - Corpus-scale full per-token dumps -> Route B (official API). Matches the
    HF loop's throughput while persisting everything; file-per-request
    output is naturally resumable. Verify numerics against a reference path
    before first scientific use, and write to a volume that fits the dump
    (a 256-text/20-layer batch is ~25 GB — think before pointing it at a
    small NVMe root disk).

Verify numerics whenever switching engines: same inputs through both paths,
cosine per vector; hooks-vs-HF measured >= 0.99999 on the machine above.

Blackwell (SM 12.x) survival settings, needed for BOTH routes as of vllm
0.22: VLLM_ATTENTION_BACKEND=TRITON_ATTN, uninstall flashinfer-python and
set VLLM_USE_FLASHINFER_SAMPLER=0, and build the venv on local disk (a
network-volume venv corrupts wheels). enforce_eager does NOT fix the SM
capability detection error; the env vars do.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jaxtyping import Float
    from torch import Tensor

# --- shared: Blackwell survival + in-process engine (Route A needs it) ----
os.environ.setdefault("VLLM_ATTENTION_BACKEND", "TRITON_ATTN")
os.environ.setdefault("VLLM_USE_FLASHINFER_SAMPLER", "0")
os.environ.setdefault("VLLM_ENABLE_V1_MULTIPROCESSING", "0")


def route_a_hooks(
    model: str, texts: list[str], layer_ids: list[int]
) -> "list[Float[Tensor, 'tokens d_model']]":
    """Forward hooks on vLLM's torch modules. Requires enforce_eager=True
    (hooks vs CUDA graphs) and the in-process engine (env var above), which
    is exactly why this route pays at capture width: every hook does a
    blocking .float().cpu() copy per forward. Numerics match the HF path
    exactly. Pool inside the hook if you only need means."""
    import torch  # local: keep module importable without a GPU env
    from vllm import LLM, SamplingParams

    llm = LLM(model=model, dtype="bfloat16", enforce_eager=True, gpu_memory_utilization=0.90)
    torch_model = llm.llm_engine.model_executor.driver_worker.model_runner.model
    # layer list location varies by architecture wrapper:
    for path in ("model.layers", "language_model.model.layers", "model.model.layers"):
        obj = torch_model
        try:
            for part in path.split("."):
                obj = getattr(obj, part)
            decoder_layers = list(obj)
            break
        except AttributeError:
            continue
    else:
        raise RuntimeError(f"no layer list on {type(torch_model).__name__}")

    captured: list[torch.Tensor] = []

    def hook(_module: object, _inputs: object, output: object) -> None:
        hidden = output[0] if isinstance(output, tuple) else output
        captured.append(hidden.detach().float().cpu())  # pool here if you can

    handles = [decoder_layers[i].register_forward_hook(hook) for i in layer_ids]
    try:
        llm.generate(texts, SamplingParams(max_tokens=1, temperature=0.0), use_tqdm=False)
    finally:
        for h in handles:
            h.remove()
    return captured


def route_b_official(model: str, texts: list[str], layer_ids: list[int], dump_dir: Path) -> Path:
    """vLLM's first-class hidden-states extraction (>= 0.18; schema below
    verified on 0.22.1 — it took three iterations against pydantic, keep it
    exact). Prefill-only, keeps CUDA graphs, writes one safetensors pair
    (token ids + [seq_len, n_layers, hidden]) per request into dump_dir."""
    from vllm import LLM, SamplingParams

    llm = LLM(
        model=model,
        dtype="bfloat16",
        gpu_memory_utilization=0.90,
        enable_chunked_prefill=False,  # documented incompatibility
        speculative_config={
            "method": "extract_hidden_states",
            "num_speculative_tokens": 1,  # asserted == 1 by the proposer
            "draft_model_config": {
                "hf_config": {"eagle_aux_hidden_state_layer_ids": layer_ids},
            },
        },
        kv_transfer_config={
            "kv_connector": "ExampleHiddenStatesConnector",
            "kv_role": "kv_producer",
            "kv_connector_extra_config": {"shared_storage_path": str(dump_dir)},
        },
    )
    llm.generate(texts, SamplingParams(max_tokens=1, temperature=0.0), use_tqdm=False)
    return dump_dir
