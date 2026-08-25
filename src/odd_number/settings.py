"""Configuration, in one typed object, read once.

`Settings` is built by `pydantic-settings` from the real environment and the
repository's `.env` file (environment wins) and validated on construction, so
a missing key fails at startup rather than as an authentication error on the
first API call. The key is a `SecretStr`: it prints as `**********` in reprs,
logs and tracebacks, and reading it requires `get_secret_value()`. The `.env`
path is resolved from this file, not the working directory, so the CLI
behaves the same from anywhere.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Final

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Repo root, derived from this file rather than the working directory.
PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """Every value this project reads from the environment.

    Field names map to upper-case environment variables automatically, so
    `openrouter_api_key` is read from `OPENROUTER_API_KEY`.
    """

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        # A .env may legitimately hold keys for other tools. Ignoring unknown
        # ones keeps this from failing on a teammate's unrelated variable.
        extra="ignore",
        frozen=True,
    )

    openrouter_api_key: SecretStr
    results_dir: Path = PROJECT_ROOT / "results"

    @property
    def api_key(self) -> str:
        """The key itself. Named so call sites read as a deliberate unwrap."""
        return self.openrouter_api_key.get_secret_value()


class MissingSettingsError(RuntimeError):
    """Configuration is absent or malformed, reported in the project's terms."""


@lru_cache(maxsize=1)
def load_settings() -> Settings:
    """Build the settings, turning a validation failure into a usable message.

    Cached because `.env` is read from disk and nothing in a single CLI
    invocation should see configuration change underneath it.

    Raises:
        MissingSettingsError: when a required value is absent. Pydantic's own
            message is accurate but describes a model, not a fix; this one names
            the two things a person can actually do about it.
    """
    try:
        return Settings()  # type: ignore[call-arg]  # values come from env/.env
    except Exception as exc:
        raise MissingSettingsError(
            f"{exc}\n\n"
            f"Set OPENROUTER_API_KEY in a gitignored .env at {PROJECT_ROOT}, "
            "export it in your shell, or run with --mock to need no key at all."
        ) from exc
