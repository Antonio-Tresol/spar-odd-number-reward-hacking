"""Configuration, in one typed object, read once.

Replaces `os.environ.get("OPENROUTER_API_KEY")` at the point of use plus a
hand-rolled `.env` parser plus a hand-written "is it missing?" check — three
mechanisms that had to agree with each other and were spread across two modules.

`pydantic-settings` does all three, and does them better:

- **Reads `.env` and the real environment, with precedence.** A shell `export`
  beats the checked-out `.env` file, so a one-off override needs no file edit.
  The hand-rolled parser got this right via `setdefault`, but only by accident
  of writing into `os.environ` first.
- **Validates on construction.** A missing key is a `ValidationError` the moment
  settings are built, which is the earliest possible point — not an
  authentication failure on the first API call, which reads like a server
  problem rather than a setup one. This is the observability contract's
  fail-fast rule (AGENTS.md rule 3) applied to credentials.
- **Parses `.env` properly.** `export KEY=value`, inline comments, quoted and
  multi-line values. The parser this replaces silently produced a variable
  named `"export OPENROUTER_API_KEY"` from the first of those, and kept the
  comment inside the value on the second.

**`SecretStr`, not `str`.** The key is a credential, and `lanorme.toml` names
leaked provider keys as a rule this project keeps on purpose. `SecretStr`
renders as `**********` in reprs, logs, and tracebacks, so an exception that
prints the settings object — or a `print(settings)` left in during debugging —
cannot leak it. Reading the real value requires saying `get_secret_value()`
explicitly, which is exactly the friction a credential should have.

The path is resolved from this file rather than the working directory, so the
CLI behaves the same run from the repo root or anywhere else.
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
