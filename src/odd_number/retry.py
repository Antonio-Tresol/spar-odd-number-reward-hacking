"""Retry policy for API calls, built on tenacity.

Division of labour: tenacity owns the *loop* — attempt counting, sleeping,
exhaustion, reraise semantics — and this module owns the *policy*, which is the
genuinely domain-specific part:

  - which failures are transient (`classify_failure`)
  - how to read a server-sent Retry-After (`wait_honouring_retry_after`)

Both need custom code under any retry library, and both are tested here. The
loop itself is not tested, because tenacity tests it.

Backoff is `wait_random_exponential`, whose own docstring states it implements
the "Full Jitter" algorithm: sleep uniformly in [0, min(base * 2**n, max)].
Fixed backoff would make several rate-limited calls retry in lockstep and
re-trigger the limit. A server-sent Retry-After always overrides the computed
value.

Usage — stack the two decorators, innermost first:

    @api_retry
    @as_transient
    def call_model(...) -> dict[str, Any]:
        ...

`as_transient` translates httpx failures into TransientError, and `api_retry`
retries exactly that type. To override settings (tests inject `sleep`):

    call_model.retry_with(sleep=recorder)(client, model, prompt)
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from typing import Final, TypeVar

import httpx
from tenacity import (
    RetryCallState,
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

LOGGER: Final[logging.Logger] = logging.getLogger("odd_number.retry")

# Retry only what is actually transient. A 400 will fail identically forever.
RETRYABLE_STATUS: Final[frozenset[int]] = frozenset({408, 409, 429, 500, 502, 503, 504})

MAX_ATTEMPTS: Final[int] = 6
BASE_DELAY: Final[float] = 1.0
MAX_DELAY: Final[float] = 60.0

T = TypeVar("T")


class TransientError(Exception):
    """A failure worth retrying, carrying Retry-After when the server sent one."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


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
    """Return a TransientError when `exc` is worth retrying, else `exc` itself."""
    if isinstance(exc, httpx.HTTPStatusError):
        if exc.response.status_code in RETRYABLE_STATUS:
            return TransientError(
                f"HTTP {exc.response.status_code}", _retry_after_seconds(exc.response)
            )
        return exc  # 400/401/403/404 — permanent, fail immediately
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return TransientError(f"{type(exc).__name__}: {exc}")
    return exc


def wait_honouring_retry_after(state: RetryCallState) -> float:
    """Full-jitter backoff, except when the server named a delay.

    A wait strategy is any callable `(RetryCallState) -> float`.
    """
    exc = state.outcome.exception() if state.outcome else None
    if isinstance(exc, TransientError) and exc.retry_after is not None:
        return min(exc.retry_after, MAX_DELAY)  # server told us; always obey it
    return wait_random_exponential(multiplier=BASE_DELAY, max=MAX_DELAY)(state)


def as_transient(fn: Callable[..., T]) -> Callable[..., T]:
    """Translate retryable failures into TransientError, leaving others alone.

    Split from the retry decorator so that "what counts as retryable" stays a
    testable pure function rather than a predicate buried in decorator config.
    """

    @functools.wraps(fn)
    def wrapper(*args: object, **kwargs: object) -> T:
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            converted = classify_failure(exc)
            if converted is exc:
                raise
            raise converted from exc

    return wrapper


#: Retry transient API failures with jittered backoff. `reraise=True` means an
#: exhausted budget surfaces the underlying TransientError rather than
#: tenacity's RetryError wrapper, so the caller sees what actually went wrong.
api_retry = retry(
    retry=retry_if_exception_type(TransientError),
    wait=wait_honouring_retry_after,
    stop=stop_after_attempt(MAX_ATTEMPTS),
    before_sleep=before_sleep_log(LOGGER, logging.WARNING),
    reraise=True,
)
