#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pytest>=8.0"]
# ///
"""Tests for check.sh itself: the gate must fail when a check fails.

The regression that motivates this file (issue #4): the two ruff steps were
one `a && b` statement, and under `set -e` a failure to the left of `&&`
aborts nothing — so a formatting failure was swallowed, the lint step never
ran, and the gate exited 0. Both this repository and a downstream project
shipped unformatted files through a green gate until a fresh clone caught it.
The gate is tested the way every check here is: it must fire on bad input and
stay quiet on clean input.

Run:  uv run tests/test_gate.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parent.parent
CHECK_SH = HARNESS / "check.sh"

UVX_STUB = """#!/usr/bin/env bash
echo "uvx $*" >> "$STUB_LOG"
case "$*" in
  *"format --check"*) exit "${FORMAT_EXIT:-0}" ;;
esac
exit 0
"""

UV_STUB = """#!/usr/bin/env bash
echo "uv $*" >> "$STUB_LOG"
exit 0
"""


def test_gate_steps_are_never_joined_with_and() -> None:
    """Under `set -e`, only the command after the final `&&` can abort, so a
    step joined to the next one has its failure swallowed. Every gate step
    stands alone as its own statement."""
    assert " && " not in CHECK_SH.read_text(encoding="utf-8")


def run_gate(tmp_path: Path, format_exit: str) -> tuple[subprocess.CompletedProcess[str], str]:
    """Run a copy of check.sh against stub uv/uvx binaries that log each call."""
    if shutil.which("bash") is None:
        pytest.skip("needs bash to exercise check.sh")
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for name, body in (("uvx", UVX_STUB), ("uv", UV_STUB)):
        stub = stubs / name
        stub.write_text(body, encoding="utf-8")
        stub.chmod(0o755)
    project = tmp_path / "project"
    project.mkdir()
    shutil.copy2(CHECK_SH, project / "check.sh")
    log = tmp_path / "calls.log"
    log.write_text("", encoding="utf-8")
    env = dict(os.environ)
    env["PATH"] = f"{stubs}{os.pathsep}{env['PATH']}"
    env["STUB_LOG"] = str(log)
    env["FORMAT_EXIT"] = format_exit
    done = subprocess.run(
        ["bash", str(project / "check.sh")],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=60,
    )
    return done, log.read_text(encoding="utf-8")


def test_a_format_failure_stops_the_gate(tmp_path: Path) -> None:
    done, calls = run_gate(tmp_path, format_exit="1")
    assert done.returncode != 0
    assert "lanorme" not in calls, "the gate continued past a failing format check"


def test_a_clean_tree_passes_and_every_step_runs(tmp_path: Path) -> None:
    done, calls = run_gate(tmp_path, format_exit="0")
    assert done.returncode == 0, done.stderr
    assert "format --check" in calls
    assert "ruff@0.15.8 check" in calls, "the lint step must run when formatting passes"
    assert "lanorme check" in calls
