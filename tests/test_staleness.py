#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pytest>=8.0", "lanorme"]
# ///
"""Tests for the staleness check, against real throwaway git repositories.

Mocking git here would test the mock. Each case builds an actual repository and
makes actual commits, which is fast enough and tests what really runs.

Run:  uv run tests/test_staleness.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lanorme_plugins.staleness import StalenessCheck  # noqa: E402


def run_git(root: Path, *args: str) -> None:
    # Scrub GIT_*: when this suite runs inside a git hook, the exported GIT_DIR
    # would point every call at the outer repository instead of the tmp repo.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, env=env)


def new_repo(root: Path) -> None:
    run_git(root, "init", "-q")
    run_git(root, "config", "user.email", "t@example.com")
    run_git(root, "config", "user.name", "T")


def commit(root: Path, relative: str, text: str, message: str = "c") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-q", "-m", message)


def warnings_of(check: StalenessCheck, root: Path) -> list[str]:
    return [w.code for w in check.run(src_root=str(root)).warnings]


# --- STALE-001 -----------------------------------------------------------


def test_fires_when_tree_falls_behind(tmp_path: Path) -> None:
    new_repo(tmp_path)
    commit(tmp_path, "TREE.md", "- Q1: q [open]\n")
    for i in range(4):
        commit(tmp_path, f"results/run{i}.json", "{}")
    check = StalenessCheck()
    check.configure(settings={"max_commits_behind": 2})
    assert "STALE-001" in warnings_of(check, tmp_path)


def test_quiet_under_the_threshold(tmp_path: Path) -> None:
    new_repo(tmp_path)
    commit(tmp_path, "TREE.md", "- Q1: q [open]\n")
    commit(tmp_path, "results/run.json", "{}")
    check = StalenessCheck()
    check.configure(settings={"max_commits_behind": 8})
    assert warnings_of(check, tmp_path) == []


def test_quiet_when_tree_keeps_pace(tmp_path: Path) -> None:
    """Updating the tree alongside the work resets the count."""
    new_repo(tmp_path)
    commit(tmp_path, "TREE.md", "- Q1: q [open]\n")
    for i in range(5):
        commit(tmp_path, f"results/run{i}.json", "{}")
    commit(tmp_path, "TREE.md", "- Q1: q [answered]\n")
    check = StalenessCheck()
    check.configure(settings={"max_commits_behind": 2})
    assert warnings_of(check, tmp_path) == []


def test_ignores_commits_outside_watched_paths(tmp_path: Path) -> None:
    """Editing docs is not evidence that the tree owes an update."""
    new_repo(tmp_path)
    commit(tmp_path, "TREE.md", "- Q1: q [open]\n")
    for i in range(6):
        commit(tmp_path, f"docs/note{i}.md", "prose")
    check = StalenessCheck()
    check.configure(settings={"max_commits_behind": 2})
    assert warnings_of(check, tmp_path) == []


def test_quiet_outside_a_git_repository(tmp_path: Path) -> None:
    (tmp_path / "TREE.md").write_text("- Q1: q [open]\n")
    assert warnings_of(StalenessCheck(), tmp_path) == []


def test_quiet_when_tree_is_absent(tmp_path: Path) -> None:
    new_repo(tmp_path)
    commit(tmp_path, "README.md", "hi")
    assert warnings_of(StalenessCheck(), tmp_path) == []


def test_quiet_when_tree_is_uncommitted(tmp_path: Path) -> None:
    """A brand new project has nothing to measure against yet."""
    new_repo(tmp_path)
    commit(tmp_path, "results/run.json", "{}")
    (tmp_path / "TREE.md").write_text("- Q1: q [open]\n")
    check = StalenessCheck()
    check.configure(settings={"max_commits_behind": 0})
    assert warnings_of(check, tmp_path) == []


# --- STALE-002 -----------------------------------------------------------

DATED = "---\ntitle: Findings\nupdated: {d}\n---\n\nBody.\n"


def test_fires_when_updated_date_is_behind(tmp_path: Path) -> None:
    new_repo(tmp_path)
    stale = date.today() - timedelta(days=30)
    commit(tmp_path, "reports/f.md", DATED.format(d=stale.isoformat()))
    check = StalenessCheck()
    check.configure(settings={"dated_docs": ["reports/**/*.md"]})
    assert "STALE-002" in warnings_of(check, tmp_path)


def test_quiet_when_updated_date_is_current(tmp_path: Path) -> None:
    new_repo(tmp_path)
    commit(tmp_path, "reports/f.md", DATED.format(d=date.today().isoformat()))
    check = StalenessCheck()
    check.configure(settings={"dated_docs": ["reports/**/*.md"]})
    assert warnings_of(check, tmp_path) == []


def test_quiet_without_an_updated_field(tmp_path: Path) -> None:
    """The field is opt-in; documents without one are not nagged."""
    new_repo(tmp_path)
    commit(tmp_path, "reports/f.md", "---\ntitle: Findings\n---\n\nBody.\n")
    check = StalenessCheck()
    check.configure(settings={"dated_docs": ["reports/**/*.md"]})
    assert warnings_of(check, tmp_path) == []


def test_stale002_off_until_dated_docs_configured(tmp_path: Path) -> None:
    new_repo(tmp_path)
    stale = (date.today() - timedelta(days=30)).isoformat()
    commit(tmp_path, "reports/f.md", DATED.format(d=stale))
    assert warnings_of(StalenessCheck(), tmp_path) == []


def test_only_configured_docs_are_dated(tmp_path: Path) -> None:
    new_repo(tmp_path)
    stale = (date.today() - timedelta(days=30)).isoformat()
    commit(tmp_path, "notes/scratch.md", DATED.format(d=stale))
    check = StalenessCheck()
    check.configure(settings={"dated_docs": ["reports/**/*.md"]})
    assert warnings_of(check, tmp_path) == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
