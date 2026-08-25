"""The configured OpenRouter client.

The official `openrouter` SDK, with exactly one retry layer: the SDK's own
`RetryConfig` already does exponential backoff with jitter, transport-error
retries and `Retry-After`, and a second layer on top would multiply attempts
and turn a rate limit into a long, expensive stall. Retryable status codes
are left at the SDK's per-operation defaults.

`x_open_router_metadata="enabled"` (off by default) makes every response
carry the served provider, the dated model actually routed to, the routing
strategy and the cost — the provenance `completions.py` reads and
`provenance.py` audits. Without it the response echoes only the bare alias
and names no provider.

Credentials are not read here; `settings.py` owns configuration.
"""

from __future__ import annotations

from typing import Final

from openrouter import OpenRouter, RetryConfig
from openrouter.utils import BackoffStrategy

from odd_number.settings import Settings, load_settings

#: Value for `x_open_router_metadata`; the module docstring says what it buys.
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
