#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pytest>=8.0"]
# ///
"""Tests for the PostToolUse validator hook shipped to projects.

The hook's contract: exit 2 with the validator's output on stderr when an
edit to the project's root TREE.md or RESEARCH_LOG.md leaves the pair
invalid; exit 0 (silently) in every other case — clean project, unrelated
file, a TREE.md that is not the project root's, or no validator present.

Run:  uv run tests/test_validate_hook.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parent.parent
HOOK = HARNESS / ".claude" / "hooks" / "validate_research_hook.py"
VALIDATOR = HARNESS / "scripts" / "validate_research.py"

CLEAN_LOG = (
    "# P\n\n## Project summary\n\nA sentence.\n\n### 2026-07-19\n\n"
    "* What I did: ran the thing.\n* What I expected vs what happened: fine.\n"
    "* What this changes about my thinking: nothing.\n* What I will do next: more.\n"
)


def project(tmp_path: Path, tree: str, with_validator: bool = True) -> Path:
    if with_validator:
        (tmp_path / "scripts").mkdir()
        shutil.copy(VALIDATOR, tmp_path / "scripts" / "validate_research.py")
    (tmp_path / "TREE.md").write_text(tree)
    (tmp_path / "RESEARCH_LOG.md").write_text(CLEAN_LOG)
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "TREE.md").write_text("# a template, not the project tree\n")
    return tmp_path


def hook(root: Path, edited: Path) -> subprocess.CompletedProcess[str]:
    payload = json.dumps({"tool_input": {"file_path": str(edited)}})
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        check=False,
        env={"CLAUDE_PROJECT_DIR": str(root), "PATH": "/usr/bin:/bin:/usr/local/bin"},
    )


def test_valid_project_stays_silent(tmp_path: Path) -> None:
    root = project(tmp_path, "- Q1: A question [open]\n")
    result = hook(root, root / "TREE.md")
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


def test_invalid_tree_blocks_with_validator_output(tmp_path: Path) -> None:
    root = project(tmp_path, "- Q1: steer w/ the scaled direction [open]\n")
    result = hook(root, root / "TREE.md")
    assert result.returncode == 2
    assert "FAIL" in result.stderr and "shorthand" in result.stderr


def test_unrelated_file_is_ignored(tmp_path: Path) -> None:
    root = project(tmp_path, "- Q1: steer w/ the scaled direction [open]\n")
    assert hook(root, root / "results.json").returncode == 0


def test_non_root_tree_is_ignored(tmp_path: Path) -> None:
    """Editing templates/TREE.md (or any other copy) must not validate the
    project: only the root pair is the hook's business."""
    root = project(tmp_path, "- Q1: steer w/ the scaled direction [open]\n")
    assert hook(root, root / "templates" / "TREE.md").returncode == 0


def test_missing_validator_is_silent(tmp_path: Path) -> None:
    root = project(tmp_path, "- Q1: q [open]\n", with_validator=False)
    assert hook(root, root / "TREE.md").returncode == 0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
