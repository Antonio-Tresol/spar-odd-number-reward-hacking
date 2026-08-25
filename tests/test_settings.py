"""Tests for configuration loading.

`settings.py` owns credentials, so the properties worth pinning are about what
happens when they are wrong or absent, and about not leaking them when they are
present.

Run:  uv run pytest tests/test_settings.py
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from odd_number.settings import MissingSettingsError, Settings, load_settings


def test_load_settings_raises_the_projects_own_error(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr("odd_number.settings.Settings", _NoEnvSettings)
    load_settings.cache_clear()
    with pytest.raises(MissingSettingsError, match="--mock"):
        load_settings()
    load_settings.cache_clear()


class _NoEnvSettings(Settings):
    """Settings with the .env disabled, so the test cannot pass by finding one."""

    model_config = {**Settings.model_config, "env_file": None}


def test_the_key_is_not_printable() -> None:
    """A traceback or a stray print must not leak the credential.

    `lanorme.toml` names leaked provider keys as a rule this project keeps on
    purpose, and reading the real value has to be an explicit act.
    """
    settings = Settings(openrouter_api_key=SecretStr("sk-or-secret"), _env_file=None)  # type: ignore[call-arg]
    assert "sk-or-secret" not in repr(settings)
    assert "sk-or-secret" not in str(settings.openrouter_api_key)
    assert settings.api_key == "sk-or-secret"


def test_results_dir_defaults_under_the_repo_not_the_cwd() -> None:
    """The CLI must behave the same run from anywhere."""
    settings = Settings(openrouter_api_key=SecretStr("k"), _env_file=None)  # type: ignore[call-arg]
    assert settings.results_dir.is_absolute()
    assert settings.results_dir.name == "results"
    assert isinstance(settings.results_dir, Path)
