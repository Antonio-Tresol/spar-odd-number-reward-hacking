"""The configured OpenRouter client.

Uses the official first-party SDK (`openrouter`, Speakeasy-generated from the
OpenAPI spec). OpenRouter explicitly does not recommend the OpenAI SDK with a
base_url override.

**One retry layer, not two.** The SDK retries internally via `RetryConfig`, and
its `BackoffStrategy` already does the whole policy this project used to
hand-roll: exponential backoff with jitter, transport-error retries, and — per
its own docstring — using a `Retry-After` or `retry-after-ms` header as-is when
the response carries one. Wrapping that in a second retry library would
multiply attempts (6 outer x N inner) and turn a rate limit into a much longer,
much more expensive stall. So the SDK owns retries and nothing sits on top.

The one behavioural difference worth knowing: the SDK's jitter is *additive*
(a random value in [0, jitter_ms] added to the computed interval) rather than
full jitter (uniform across [0, cap]). Additive jitter decorrelates retries
less aggressively. It is fine at this scale — a handful of sequential calls,
not a fleet — but it is a real difference, not an equivalence.

Retryable status codes are left at the SDK's per-operation defaults rather than
overridden: those come from the OpenAPI spec, and hand-listing them risks
retrying something permanent like a 400, which fails identically forever.
"""

from __future__ import annotations

import os
from typing import Final

from openrouter import OpenRouter, RetryConfig
from openrouter.utils import BackoffStrategy

# Milliseconds throughout — the SDK's unit.
INITIAL_INTERVAL_MS: Final[int] = 1_000
MAX_INTERVAL_MS: Final[int] = 60_000
MAX_ELAPSED_MS: Final[int] = 300_000
JITTER_MS: Final[int] = 1_000
EXPONENT: Final[float] = 2.0

#: A single rollout can be a long reasoning trace, so allow generous time.
REQUEST_TIMEOUT_MS: Final[int] = 300_000


def retry_config() -> RetryConfig:
    """Backoff policy for transient API failures."""
    return RetryConfig(
        strategy="backoff",
        backoff=BackoffStrategy(
            initial_interval=INITIAL_INTERVAL_MS,
            max_interval=MAX_INTERVAL_MS,
            exponent=EXPONENT,
            max_elapsed_time=MAX_ELAPSED_MS,
            jitter_ms=JITTER_MS,
        ),
        retry_connection_errors=True,
    )


def build_client(api_key: str | None = None) -> OpenRouter:
    """Construct the client, failing loudly if the key is missing.

    Raises:
        RuntimeError: when no API key is available. Better here than as an
            authentication error on the first call, which reads like a server
            problem rather than a setup one.
    """
    key = api_key or os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. Put it in a gitignored .env, or pass --mock."
        )
    return OpenRouter(
        api_key=key,
        retry_config=retry_config(),
        timeout_ms=REQUEST_TIMEOUT_MS,
    )
