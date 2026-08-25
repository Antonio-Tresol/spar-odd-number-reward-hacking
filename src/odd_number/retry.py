"""Retry policy for API calls.

Follows `.claude/skills/experiment-engineering/references/api_runner.py` (sync
adaptation), which is the convention AGENTS.md points at for any script that
spends API budget. Not tenacity: the two behaviours that actually matter here —
obeying a server-sent `Retry-After`, and retrying only genuinely transient
statuses — need custom predicates under tenacity anyway.
"""

from __future__ import annotations

import random
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

import httpx

# Retry only what is actually transient. A 400 will fail identically forever.
RETRYABLE_STATUS: Final[frozenset[int]] = frozenset({408, 409, 429, 500, 502, 503, 504})


class TransientError(Exception):
    """A failure worth retrying, carrying Retry-After when the server sent one."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Exponential backoff with FULL jitter.

    Full jitter (sleep uniformly in [0, delay]) rather than a fixed delay matters
    when several calls get rate-limited at once: without it they retry in
    lockstep and re-trigger the limit.
    """

    max_attempts: int = 6
    base_delay: float = 1.0
    max_delay: float = 60.0

    def delay_for(self, attempt: int, retry_after: float | None = None) -> float:
        if retry_after is not None:  # server told us; always obey it
            return min(retry_after, self.max_delay)
        capped = min(self.base_delay * (2**attempt), self.max_delay)
        return random.uniform(0.0, capped)


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """Parse Retry-After, which may be seconds or an HTTP date. Seconds only."""
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None  # HTTP-date form; fall back to computed backoff


def classify_failure(exc: Exception) -> Exception:
    """Convert an httpx failure into TransientError when it is worth retrying."""
    if isinstance(exc, httpx.HTTPStatusError):
        if exc.response.status_code in RETRYABLE_STATUS:
            return TransientError(
                f"HTTP {exc.response.status_code}", _retry_after_seconds(exc.response)
            )
        return exc  # 400/401/403/404 — permanent, fail immediately
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return TransientError(f"{type(exc).__name__}: {exc}")
    return exc


def with_retries(
    operation: Callable[[], dict[str, Any]], policy: RetryPolicy, label: str
) -> dict[str, Any]:
    """Run `operation`, retrying transient failures with jittered backoff."""
    last: Exception | None = None
    for attempt in range(policy.max_attempts):
        try:
            return operation()
        except Exception as exc:  # noqa: BLE001 — re-raised unless transient
            converted = classify_failure(exc)
            if not isinstance(converted, TransientError):
                raise
            last = converted
            if attempt == policy.max_attempts - 1:
                break
            delay = policy.delay_for(attempt, converted.retry_after)
            print(
                f"    {label}: transient ({attempt + 1}/{policy.max_attempts}), "
                f"sleeping {delay:.1f}s: {converted}",
                file=sys.stderr,
            )
            time.sleep(delay)
    raise RuntimeError(f"{label}: exhausted {policy.max_attempts} attempts") from last
