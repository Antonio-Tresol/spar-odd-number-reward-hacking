#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Reference implementation: GPU memory measurement and OOM-safe batching.

Torch is imported lazily so this file can be read, linted, and unit-tested on a
machine with no GPU. Copy the pieces you need.

The failures this prevents:

  * "it OOMed at hour 3 of a 4-hour run" — adaptive batching halves and retries
    instead of dying, and a checkpoint means you resume rather than restart.
  * "it worked yesterday" — peak memory is measured and logged per run, so a
    creeping regression is visible before it becomes a crash.
  * "the batch size that worked for short prompts OOMs on long ones" — attention
    memory grows with the SQUARE of sequence length, so batch size must be chosen
    against your LONGEST sequence, not your average.
  * silent fragmentation — `empty_cache()` between phases, and reserved-vs-allocated
    logged separately so you can tell a real leak from a caching artifact.
"""

from __future__ import annotations

import gc
import logging
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Final, TypeVar

LOGGER: Final[logging.Logger] = logging.getLogger("gpu")
BYTES_PER_GIB: Final[float] = 1024**3

T = TypeVar("T")
R = TypeVar("R")


def _torch() -> Any:
    """Import torch on demand so this module is importable without a GPU."""
    import torch  # noqa: PLC0415 — deliberate lazy import

    return torch


def is_cuda_available() -> bool:
    try:
        return bool(_torch().cuda.is_available())
    except ImportError:
        return False


@dataclass(frozen=True)
class MemorySnapshot:
    """GPU memory in GiB.

    `allocated` is what tensors actually hold; `reserved` is what the caching
    allocator has taken from the driver. Reserved >> allocated means
    fragmentation, not a leak — the distinction that saves hours of wrong debugging.
    """

    allocated: float
    reserved: float
    peak_allocated: float
    total: float

    @property
    def free(self) -> float:
        return self.total - self.reserved

    def render(self) -> str:
        return (
            f"allocated {self.allocated:.2f}GiB | reserved {self.reserved:.2f}GiB | "
            f"peak {self.peak_allocated:.2f}GiB | free {self.free:.2f}GiB / {self.total:.2f}GiB"
        )


def snapshot(device: int = 0) -> MemorySnapshot | None:
    """Current memory state, or None when there is no GPU."""
    if not is_cuda_available():
        return None
    torch = _torch()
    return MemorySnapshot(
        allocated=torch.cuda.memory_allocated(device) / BYTES_PER_GIB,
        reserved=torch.cuda.memory_reserved(device) / BYTES_PER_GIB,
        peak_allocated=torch.cuda.max_memory_allocated(device) / BYTES_PER_GIB,
        total=torch.cuda.get_device_properties(device).total_memory / BYTES_PER_GIB,
    )


def free_memory() -> None:
    """Drop cached blocks. Call between phases, not inside a hot loop — it syncs."""
    gc.collect()
    if is_cuda_available():
        _torch().cuda.empty_cache()


@contextmanager
def track_memory(label: str, device: int = 0) -> Iterator[None]:
    """Log peak memory for a block of work.

    Peak is what determines whether you OOM, and it is invariably higher than
    what you see after the fact — measure it, don't estimate it.
    """
    if not is_cuda_available():
        LOGGER.debug("%s: no CUDA device, memory tracking skipped", label)
        yield
        return
    torch = _torch()
    torch.cuda.reset_peak_memory_stats(device)
    before = snapshot(device)
    try:
        yield
    finally:
        after = snapshot(device)
        if before is not None and after is not None:
            LOGGER.info(
                "%s: peak %.2fGiB (delta allocated %+.2fGiB) | %s",
                label,
                after.peak_allocated,
                after.allocated - before.allocated,
                after.render(),
            )


def is_oom_error(exc: BaseException) -> bool:
    """True for CUDA OOM, which is recoverable, unlike other runtime errors."""
    if exc.__class__.__name__ == "OutOfMemoryError":
        return True
    return isinstance(exc, RuntimeError) and "out of memory" in str(exc).lower()


@dataclass(frozen=True)
class BatchPlan:
    """Batching parameters, chosen once and logged with the run."""

    initial_size: int
    min_size: int = 1

    def halved(self, size: int) -> int:
        return max(self.min_size, size // 2)


def run_in_batches(
    items: Sequence[T],
    process: Callable[[Sequence[T]], Sequence[R]],
    plan: BatchPlan,
    on_batch_done: Callable[[int, Sequence[R]], None] | None = None,
) -> list[R]:
    """Process items in batches, halving the batch size on OOM instead of dying.

    `on_batch_done(start_index, results)` is where you persist incrementally —
    an OOM at item 9000 of 10000 should cost one batch, not the whole run.
    """
    results: list[R] = []
    size = plan.initial_size
    index = 0
    while index < len(items):
        batch = items[index : index + size]
        try:
            produced = process(batch)
        except Exception as exc:
            if not is_oom_error(exc) or size <= plan.min_size:
                raise
            free_memory()
            size = plan.halved(size)
            LOGGER.warning("OOM at index %d — retrying with batch size %d", index, size)
            continue
        results.extend(produced)
        if on_batch_done is not None:
            on_batch_done(index, produced)
        index += len(batch)
    return results


def find_max_batch_size(
    probe: Callable[[int], None],
    upper_bound: int,
    lower_bound: int = 1,
) -> int:
    """Binary-search the largest batch size that does not OOM.

    Run this ONCE against your worst case — longest sequences, longest generation
    — and then hardcode the result with a safety margin. Probing on average-length
    input produces a number that OOMs later on the tail.
    """
    best = lower_bound
    low, high = lower_bound, upper_bound
    while low <= high:
        mid = (low + high) // 2
        free_memory()
        try:
            probe(mid)
        except Exception as exc:
            if not is_oom_error(exc):
                raise
            high = mid - 1
            LOGGER.debug("batch size %d OOMs", mid)
            continue
        best = mid
        low = mid + 1
        LOGGER.debug("batch size %d fits", mid)
    free_memory()
    LOGGER.info("max batch size found: %d (probe upper bound %d)", best, upper_bound)
    return best


def sort_by_length(items: Sequence[T], length_of: Callable[[T], int]) -> list[int]:
    """Indices sorted by length, longest first.

    Two wins: batches become length-homogeneous so padding waste collapses, and
    the biggest batch runs FIRST — so if the run is going to OOM, it does so in
    the first minute rather than an hour in.
    """
    return sorted(range(len(items)), key=lambda i: length_of(items[i]), reverse=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(name)s | %(message)s")
    state = snapshot()
    LOGGER.info("CUDA available: %s", is_cuda_available())
    if state is not None:
        LOGGER.info("memory: %s", state.render())

    # Demonstrates the batching loop with a fake OOM on large batches.
    def fake_process(batch: Sequence[int]) -> list[int]:
        if len(batch) > 4:
            raise RuntimeError("CUDA out of memory (simulated)")
        return [x * 2 for x in batch]

    out = run_in_batches(list(range(20)), fake_process, BatchPlan(initial_size=16))
    LOGGER.info("processed %d items, first five: %s", len(out), out[:5])
