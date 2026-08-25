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

## Response metadata

`x_open_router_metadata` is OFF by default, and turning it on is what makes
provenance cheap. With it enabled every response carries `openrouter_metadata`:
the served provider, the *dated* model actually routed to, the routing strategy,
and the cost. Without it, `ChatResult.model` echoes only the bare alias and there
is no provider field at all — which previously forced a second, lagged API call
per rollout just to learn who served it. One header replaced that entirely.

Credentials are not read here; `settings.py` owns configuration.
"""

from __future__ import annotations

from typing import Final

from openrouter import OpenRouter, RetryConfig
from openrouter.utils import BackoffStrategy

from odd_number.settings import Settings, load_settings

#: Value for `x_open_router_metadata`. See "Response metadata" above.
#: The SDK types this as a literal — "enabled" or "disabled", not a bool.
METADATA_ENABLED: Final[str] = "enabled"

# Milliseconds throughout — the SDK's unit.
INITIAL_INTERVAL_MS: Final[int] = 1_000
MAX_INTERVAL_MS: Final[int] = 60_000
MAX_ELAPSED_MS: Final[int] = 300_000
JITTER_MS: Final[int] = 1_000
EXPONENT: Final[float] = 2.0

#: A single rollout can be a long reasoning trace, so allow generous time.
REQUEST_TIMEOUT_MS: Final[int] = 300_000


def build_retry_config() -> RetryConfig:
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


def build_client(settings: Settings | None = None) -> OpenRouter:
    """Construct the client from validated settings.

    Credentials are not read here. `settings.py` owns where configuration comes
    from and raises `MissingSettingsError` if it is absent, so this function
    cannot disagree with it about precedence or about what "missing" means —
    which is the failure mode of having a key check in two places.
    """
    resolved = settings or load_settings()
    return OpenRouter(
        api_key=resolved.api_key,
        retry_config=build_retry_config(),
        timeout_ms=REQUEST_TIMEOUT_MS,
    )
