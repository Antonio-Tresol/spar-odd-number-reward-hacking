#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["jaxtyping>=0.2", "einops>=0.8", "numpy>=1.26"]
# ///
"""Reference: jaxtyping annotations and einops operations on tensors.

Every tensor — including a vector, which is just a rank-1 tensor — carries its
shape in its type. The demo below runs on numpy so it installs in seconds; the
annotations are identical for torch (`from torch import Tensor`), which is the
usual target.

Why this is worth the keystrokes:

  * A shape bug caught by reading a signature costs seconds. The same bug found
    by debugging a silently-broadcast result costs an afternoon — and the worst
    case is it never errors at all, just quietly computes the wrong number.
  * Named axes ARE the documentation. `Float[Tensor, "batch seq d_model"]` says
    what `torch.Tensor` never could, and jaxtyping checks it at runtime when the
    typechecker decorator is active.
  * einops operations state intent. `rearrange(x, "b s d -> b d s")` is checkable
    and self-explaining; `x.permute(0, 2, 1)` is a puzzle with an off-by-one trap.

Convention used throughout the harness:

    b = batch      s = sequence position   d = model dimension (d_model)
    h = heads      v = vocabulary          l = layers            f = features

Keep axis names consistent within a project — the names are an interface.
"""

from __future__ import annotations

import logging
from typing import Final

import numpy as np
from einops import einsum, rearrange, reduce, repeat
from jaxtyping import Bool, Float, Int

LOGGER: Final[logging.Logger] = logging.getLogger("tensors")

# Alias for the array type. Porting to torch means importing Tensor from torch
# and pointing this alias at it — every annotation below is otherwise unchanged,
# e.g. Float[Array, "batch seq d_model"] reads identically either way.
Array = np.ndarray


def mean_pool(
    activations: Float[Array, "batch seq d_model"],
    mask: Bool[Array, "batch seq"],
) -> Float[Array, "batch d_model"]:
    """Mean over unmasked positions.

    The annotations make the contract explicit: the mask is per-position, not
    per-feature, and the sequence axis disappears. A mask of the wrong rank is
    the classic silent-broadcast bug this prevents.
    """
    weights: Float[Array, "batch seq 1"] = rearrange(mask.astype(activations.dtype), "b s -> b s 1")
    masked: Float[Array, "batch seq d_model"] = activations * weights
    totals: Float[Array, "batch d_model"] = reduce(masked, "b s d -> b d", "sum")
    counts: Float[Array, "batch 1"] = reduce(weights, "b s 1 -> b 1", "sum")
    return totals / np.clip(counts, 1.0, None)


def split_heads(
    hidden: Float[Array, "batch seq d_model"],
    num_heads: int,
) -> Float[Array, "batch heads seq head_dim"]:
    """Split d_model into heads.

    einops names the split, so the head/head_dim ordering cannot be silently
    transposed the way a bare `.view(b, s, h, -1).permute(0, 2, 1, 3)` can be.
    """
    return rearrange(hidden, "b s (h d) -> b h s d", h=num_heads)


def project_to_direction(
    activations: Float[Array, "batch seq d_model"],
    direction: Float[Array, "d_model"],
) -> Float[Array, "batch seq"]:
    """Project activations onto a single direction.

    `direction` is a VECTOR and still gets a full annotation — rank 1 is a shape
    too, and mixing up d_model with, say, a per-head dimension is exactly the
    error the annotation catches.
    """
    return einsum(activations, direction, "b s d, d -> b s")


def unit(vector: Float[Array, "d_model"]) -> Float[Array, "d_model"]:
    """Normalize a direction vector to unit length."""
    norm = float(np.linalg.norm(vector))
    if norm == 0.0:
        raise ValueError("cannot normalize a zero vector")
    return vector / norm


def broadcast_direction(
    direction: Float[Array, "d_model"],
    batch: int,
    seq: int,
) -> Float[Array, "batch seq d_model"]:
    """Explicitly materialize a direction across batch and sequence.

    `repeat` states the intent; relying on implicit broadcasting is where a
    wrong-axis bug hides without ever raising.
    """
    return repeat(direction, "d -> b s d", b=batch, s=seq)


def top_k_indices(scores: Float[Array, "batch vocab"], k: int) -> Int[Array, "batch k"]:
    """Indices of the k highest scores per row."""
    return np.argsort(-scores, axis=-1)[:, :k]


def _demo() -> None:
    rng = np.random.default_rng(0)
    batch, seq, d_model, heads = 4, 7, 12, 3

    activations: Float[Array, "batch seq d_model"] = rng.normal(size=(batch, seq, d_model))
    mask: Bool[Array, "batch seq"] = rng.random((batch, seq)) > 0.3
    direction: Float[Array, "d_model"] = unit(rng.normal(size=d_model))

    pooled = mean_pool(activations, mask)
    heads_split = split_heads(activations, heads)
    projections = project_to_direction(activations, direction)
    broadcast = broadcast_direction(direction, batch, seq)
    top = top_k_indices(rng.normal(size=(batch, 20)), k=3)

    LOGGER.info("activations %s -> pooled %s", activations.shape, pooled.shape)
    LOGGER.info("split into %d heads: %s", heads, heads_split.shape)
    LOGGER.info(
        "projections %s | broadcast %s | top-k %s", projections.shape, broadcast.shape, top.shape
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(name)s | %(message)s")
    _demo()
