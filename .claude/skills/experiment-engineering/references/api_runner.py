#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Reference implementation: concurrent API calls done safely.

Copy this into a project and adapt `call_one`. It gives you, in one place, the
things that otherwise get rediscovered painfully mid-run:

  * bounded concurrency (a semaphore, not an unbounded gather)
  * exponential backoff with full jitter, honouring Retry-After
  * a disk cache so a killed run resumes instead of re-paying for tokens
  * incremental .jsonl output written as results land
  * per-item error capture — one failure never kills the batch
  * ETA logged to a FILE at intervals, so progress survives a dropped SSH session

Deliberately dependency-free (no tqdm/httpx) so it can be dropped anywhere; swap
`asyncio.sleep`-based fake work for a real client call.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import random
import sys
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

LOGGER: Final[logging.Logger] = logging.getLogger("api_runner")

# Retry only what is actually transient. A 400 will fail identically forever.
RETRYABLE_STATUS: Final[frozenset[int]] = frozenset({408, 409, 429, 500, 502, 503, 504})


class TransientError(Exception):
    """Raised by a call wrapper when the failure is worth retrying."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


@dataclass(frozen=True)
class RetryPolicy:
    """Exponential backoff with FULL jitter.

    Full jitter (sleep uniformly in [0, delay]) rather than fixed delay matters
    when many workers get rate-limited at once: without it they all retry in
    lockstep and re-trigger the limit — a thundering herd of your own making.
    """

    max_attempts: int = 6
    base_delay: float = 1.0
    max_delay: float = 60.0

    def delay_for(self, attempt: int, retry_after: float | None = None) -> float:
        if retry_after is not None:  # server told us; always obey it
            return min(retry_after, self.max_delay)
        capped = min(self.base_delay * (2**attempt), self.max_delay)
        return random.uniform(0.0, capped)


@dataclass
class Progress:
    """Counts completions and logs an ETA line periodically.

    A tqdm bar on stderr is invisible in a nohup log; this writes ETA through the
    logger so a detached or resumed run still reports where it is.
    """

    total: int
    log_every: int = 25
    started: float = field(default_factory=time.monotonic)
    done: int = 0
    failed: int = 0
    cached: int = 0

    def record(self, *, ok: bool, from_cache: bool = False) -> None:
        self.done += 1
        if not ok:
            self.failed += 1
        if from_cache:
            self.cached += 1
        if self.done % self.log_every == 0 or self.done == self.total:
            LOGGER.info(self.render())

    def render(self) -> str:
        elapsed = time.monotonic() - self.started
        rate = self.done / elapsed if elapsed > 0 else 0.0
        remaining = (self.total - self.done) / rate if rate > 0 else float("inf")
        return (
            f"{self.done}/{self.total} "
            f"({self.done / self.total:.1%}) | "
            f"{rate:.2f} it/s | "
            f"elapsed {format_duration(elapsed)} | "
            f"ETA {format_duration(remaining)} | "
            f"failed {self.failed} | cached {self.cached}"
        )


def format_duration(seconds: float) -> str:
    if seconds == float("inf"):
        return "unknown"
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:d}h{minutes:02d}m{secs:02d}s" if hours else f"{minutes:d}m{secs:02d}s"


def cache_key(payload: object) -> str:
    """Stable hash of a request. Sort keys so dict ordering can't split the cache."""
    blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:20]


class DiskCache:
    """One file per response. Crude, dependency-free, and enough.

    The point is resumability: kill the script, re-run it, and only the
    uncompleted work costs money.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, key: str) -> Path:
        return self.root / f"{key}.json"

    def get(self, key: str) -> object | None:
        path = self.path_for(key)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:  # truncated by an earlier kill
            path.unlink(missing_ok=True)
            return None

    def put(self, key: str, value: object) -> None:
        # Write to a temp file then rename: an interrupted write must not leave a
        # half-written cache entry that later reads as valid.
        tmp = self.path_for(key).with_suffix(".tmp")
        tmp.write_text(json.dumps(value))
        tmp.replace(self.path_for(key))


async def with_retries(
    operation: Callable[[], Awaitable[object]],
    policy: RetryPolicy,
    label: str,
) -> object:
    """Run `operation`, retrying transient failures with backoff."""
    last_error: Exception | None = None
    for attempt in range(policy.max_attempts):
        try:
            return await operation()
        except TransientError as exc:
            last_error = exc
            if attempt == policy.max_attempts - 1:
                break
            delay = policy.delay_for(attempt, exc.retry_after)
            LOGGER.warning(
                "%s: transient failure (attempt %d/%d), sleeping %.1fs: %s",
                label,
                attempt + 1,
                policy.max_attempts,
                delay,
                exc,
            )
            await asyncio.sleep(delay)
    raise RuntimeError(f"{label}: exhausted {policy.max_attempts} attempts") from last_error


class JsonlWriter:
    """Append-only results file, flushed per row.

    Flushing every row is the difference between a crash at 90% costing nothing
    and costing 90% of the run.
    """

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = path.open("a", encoding="utf-8")
        self._lock = asyncio.Lock()

    async def write(self, row: dict[str, object]) -> None:
        async with self._lock:
            self._handle.write(json.dumps(row, default=str) + "\n")
            self._handle.flush()

    def close(self) -> None:
        self._handle.close()


@dataclass(frozen=True)
class RunnerConfig:
    out_path: Path
    cache_dir: Path
    concurrency: int = 8
    policy: RetryPolicy = field(default_factory=RetryPolicy)


class Runner:
    """Drives a list of items through a call function, concurrently and safely."""

    def __init__(
        self, config: RunnerConfig, call_one: Callable[[object], Awaitable[object]]
    ) -> None:
        self.config = config
        self.call_one = call_one
        self.cache = DiskCache(config.cache_dir)
        self.semaphore = asyncio.Semaphore(config.concurrency)

    async def _resolve(self, item: object, key: str) -> tuple[object, bool]:
        """Return (result, from_cache)."""
        hit = self.cache.get(key)
        if hit is not None:
            return hit, True
        async with self.semaphore:
            result = await with_retries(lambda: self.call_one(item), self.config.policy, key)
        self.cache.put(key, result)
        return result, False

    async def _process(
        self, index: int, item: object, writer: JsonlWriter, progress: Progress
    ) -> None:
        key = cache_key(item)
        row: dict[str, object] = {"index": index, "key": key, "input": item}
        try:
            result, from_cache = await self._resolve(item, key)
            row["output"] = result
            row["cached"] = from_cache
            await writer.write(row)
            progress.record(ok=True, from_cache=from_cache)
        except Exception as exc:  # one item's failure must not kill the batch
            LOGGER.exception("item %d failed permanently", index)
            row["error"] = f"{type(exc).__name__}: {exc}"
            await writer.write(row)
            progress.record(ok=False)

    async def run(self, items: Sequence[object]) -> Progress:
        writer = JsonlWriter(self.config.out_path)
        progress = Progress(total=len(items))
        LOGGER.info("starting %d items, concurrency=%d", len(items), self.config.concurrency)
        try:
            await asyncio.gather(
                *(self._process(i, item, writer, progress) for i, item in enumerate(items))
            )
        finally:
            writer.close()
        LOGGER.info("finished: %s", progress.render())
        return progress


def setup_logging(log_path: Path, level: int = logging.INFO) -> None:
    """Log to a file AND stderr. A scrolled-away terminal is not a record."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
        handlers=[logging.FileHandler(log_path), logging.StreamHandler(sys.stderr)],
    )


async def demo_call(item: object) -> dict[str, object]:
    """Stand-in for a real client call. Replace with your provider's SDK.

    A real wrapper should translate the provider's rate-limit and 5xx errors into
    TransientError (passing Retry-After when the response carries it), and let
    everything else propagate so it is not retried pointlessly.
    """
    await asyncio.sleep(random.uniform(0.05, 0.2))
    if random.random() < 0.15:
        raise TransientError("simulated 429", retry_after=None)
    return {"echo": item}


async def main_async(count: int, out_dir: Path) -> int:
    setup_logging(out_dir / "run.log")
    config = RunnerConfig(
        out_path=out_dir / "results.jsonl",
        cache_dir=out_dir / "cache",
        concurrency=8,
    )
    runner = Runner(config, demo_call)
    progress = await runner.run([{"prompt": f"item {i}"} for i in range(count)])
    return 1 if progress.failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--out-dir", type=Path, default=Path("results/api_demo"))
    args = parser.parse_args()
    return asyncio.run(main_async(args.count, args.out_dir))


if __name__ == "__main__":
    sys.exit(main())
