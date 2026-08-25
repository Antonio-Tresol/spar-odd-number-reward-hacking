#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pytest>=8.0", "lanorme"]
# ///
"""Tests for the notebooks check: report notebooks pass the same gates as code.

Same contract as test_checks.py: every rule must FIRE on what it is meant to
catch and STAY QUIET on realistic input it should not touch. The quiet tests
matter more — a notebook gate that cries wolf on magics, markdown cells, or
archived explore-mode notebooks would be excluded wholesale and catch nothing.

Run:  uv run tests/test_notebooks.py       (or: uv run --with pytest pytest tests/)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lanorme_plugins import tensors  # noqa: E402,F401 — registers the tensors check
from lanorme_plugins.notebooks import NotebooksCheck  # noqa: E402


def write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def write_nb(root: Path, relative: str, cells: list[tuple[str, str]]) -> Path:
    """Write a minimal .ipynb; cells are (cell_type, source) pairs."""
    payload = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {},
        "cells": [
            {"cell_type": kind, "metadata": {}, "source": source.splitlines(keepends=True)}
            | ({"outputs": [], "execution_count": None} if kind == "code" else {})
            for kind, source in cells
        ],
    }
    return write(root, relative, json.dumps(payload))


def codes(result: object) -> list[str]:
    """Rule codes reported, violations and warnings together."""
    return [v.code for v in [*result.violations, *result.warnings]]  # type: ignore[attr-defined]


def findings(result: object) -> list[object]:
    return [*result.violations, *result.warnings]  # type: ignore[attr-defined]


# --------------------------------------------------------------------------
# Fires: the gates the .py checks enforce reach notebook code cells too.
# --------------------------------------------------------------------------


def test_fires_on_bare_container_annotation_in_a_cell(tmp_path: Path) -> None:
    write_nb(
        tmp_path,
        "notebooks/report.ipynb",
        [("code", "def load(rows: dict) -> dict:\n    return rows\n")],
    )
    assert "TYPE-002" in codes(NotebooksCheck().run(src_root=str(tmp_path)))


def test_fires_on_dangerous_calls_in_a_cell(tmp_path: Path) -> None:
    write_nb(
        tmp_path,
        "notebooks/report.ipynb",
        [("code", "import os\n\nos.system('rm -rf outputs')\n")],
    )
    assert "SHELL-001" in codes(NotebooksCheck().run(src_root=str(tmp_path)))


def test_fires_on_tensor_rules_when_import_is_in_an_earlier_cell(tmp_path: Path) -> None:
    """The reason cells are concatenated: TENSOR rules are gated on a tensor
    import, and in a notebook the import lives cells above the usage."""
    write_nb(
        tmp_path,
        "notebooks/report.ipynb",
        [
            ("code", "import torch\n"),
            ("markdown", "## Reshape\n"),
            ("code", "def widen(x):\n    return x.view(1, -1)\n"),
        ],
    )
    assert "TENSOR-002" in codes(NotebooksCheck().run(src_root=str(tmp_path)))


def test_reports_notebook_path_and_cell_relative_line(tmp_path: Path) -> None:
    write_nb(
        tmp_path,
        "notebooks/report.ipynb",
        [
            ("code", "import json\n"),
            ("code", "# a comment\ndef load(rows: dict) -> dict:\n    return rows\n"),
        ],
    )
    result = NotebooksCheck().run(src_root=str(tmp_path))
    hits = [v for v in findings(result) if v.code == "TYPE-002"]
    assert hits, codes(result)
    assert hits[0].file == "notebooks/report.ipynb"
    assert hits[0].line == 2  # line within the cell, not within the flattened module
    assert "code cell 2" in hits[0].message


def test_broken_cell_warns_but_other_cells_are_still_checked(tmp_path: Path) -> None:
    write_nb(
        tmp_path,
        "notebooks/report.ipynb",
        [
            ("code", "def broken(:\n"),
            ("code", "def load(rows: dict) -> dict:\n    return rows\n"),
        ],
    )
    found = codes(NotebooksCheck().run(src_root=str(tmp_path)))
    assert "NB-000" in found and "TYPE-002" in found


def test_unreadable_notebook_warns_instead_of_crashing(tmp_path: Path) -> None:
    write(tmp_path, "notebooks/corrupt.ipynb", "{not json")
    result = NotebooksCheck().run(src_root=str(tmp_path))
    assert codes(result) == ["NB-000"]


# --------------------------------------------------------------------------
# Quiet: what must NOT attract findings.
# --------------------------------------------------------------------------


def test_quiet_on_a_clean_notebook(tmp_path: Path) -> None:
    write_nb(
        tmp_path,
        "notebooks/report.ipynb",
        [
            ("markdown", "# Results\n"),
            ("code", "def total(counts: list[int]) -> int:\n    return sum(counts)\n"),
        ],
    )
    assert codes(NotebooksCheck().run(src_root=str(tmp_path))) == []


def test_quiet_on_python_looking_code_in_markdown_cells(tmp_path: Path) -> None:
    """Markdown showing bad code is documentation, not code."""
    write_nb(
        tmp_path,
        "notebooks/report.ipynb",
        [("markdown", "```python\nimport os\nos.system('x')\ndef f(d: dict): ...\n```\n")],
    )
    assert codes(NotebooksCheck().run(src_root=str(tmp_path))) == []


def test_quiet_on_line_magics_shell_escapes_and_cell_magics(tmp_path: Path) -> None:
    """IPython syntax is not Python; it must be neutralised, not reported as
    a parse failure (NB-000 on every real notebook would drown the signal)."""
    write_nb(
        tmp_path,
        "notebooks/report.ipynb",
        [
            ("code", "%%bash\nls -la\n"),
            ("code", "%matplotlib inline\n!du -sh data\nanswer: int = 42\n"),
        ],
    )
    assert codes(NotebooksCheck().run(src_root=str(tmp_path))) == []


def test_archive_notebooks_are_exempt_by_default(tmp_path: Path) -> None:
    write_nb(
        tmp_path,
        "notebooks/archive/bench.ipynb",
        [("code", "import os\nos.system('x')\ndef f(d: dict): ...\n")],
    )
    assert codes(NotebooksCheck().run(src_root=str(tmp_path))) == []


def test_exclude_globs_are_configurable(tmp_path: Path) -> None:
    write_nb(tmp_path, "explore/scratch.ipynb", [("code", "def f(d: dict): ...\n")])
    check = NotebooksCheck()
    check.configure(settings={"exclude": ["explore/**"]})
    assert codes(check.run(src_root=str(tmp_path))) == []


# --------------------------------------------------------------------------
# Ruff parity: the notebooks ruff formats are exactly the notebooks gated.
# --------------------------------------------------------------------------


def test_respects_ruff_extend_exclude_from_pyproject(tmp_path: Path) -> None:
    write(
        tmp_path,
        "pyproject.toml",
        '[tool.ruff]\nextend-exclude = ["notebooks/old"]\n',
    )
    write_nb(tmp_path, "notebooks/old/draft.ipynb", [("code", "def f(d: dict): ...\n")])
    write_nb(tmp_path, "notebooks/report.ipynb", [("code", "def g(d: dict): ...\n")])
    result = NotebooksCheck().run(src_root=str(tmp_path))
    assert {v.file for v in findings(result)} == {"notebooks/report.ipynb"}


def test_respects_ruff_basename_pattern_from_ruff_toml(tmp_path: Path) -> None:
    """A slashless ruff pattern (`*.ipynb`, the harness's own config) matches
    by basename anywhere in the tree — every notebook stays explore-mode."""
    write(tmp_path, "ruff.toml", 'exclude = ["*.ipynb"]\n')
    write_nb(tmp_path, "notebooks/report.ipynb", [("code", "def f(d: dict): ...\n")])
    assert codes(NotebooksCheck().run(src_root=str(tmp_path))) == []


def test_ruff_excludes_can_be_ignored_by_config(tmp_path: Path) -> None:
    write(tmp_path, "ruff.toml", 'exclude = ["*.ipynb"]\n')
    write_nb(tmp_path, "notebooks/report.ipynb", [("code", "def f(d: dict): ...\n")])
    check = NotebooksCheck()
    check.configure(settings={"respect_ruff_excludes": False})
    assert "TYPE-002" in codes(check.run(src_root=str(tmp_path)))


# --------------------------------------------------------------------------
# Configuration of the sub-check list.
# --------------------------------------------------------------------------


def test_check_list_is_configurable(tmp_path: Path) -> None:
    write_nb(
        tmp_path,
        "notebooks/report.ipynb",
        [("code", "import os\nos.system('x')\ndef f(d: dict): ...\n")],
    )
    check = NotebooksCheck()
    check.configure(settings={"checks": ["security_calls"]})
    found = codes(check.run(src_root=str(tmp_path)))
    assert "SHELL-001" in found and "TYPE-002" not in found


def test_disabled_check_reports_nothing(tmp_path: Path) -> None:
    write_nb(tmp_path, "notebooks/report.ipynb", [("code", "def f(d: dict): ...\n")])
    check = NotebooksCheck()
    check.configure(settings={"enabled": False})
    assert codes(check.run(src_root=str(tmp_path))) == []


def test_never_recurses_into_itself(tmp_path: Path) -> None:
    write_nb(tmp_path, "notebooks/report.ipynb", [("code", "x: int = 1\n")])
    check = NotebooksCheck()
    check.configure(settings={"checks": ["notebooks", "strong_types"]})
    assert codes(check.run(src_root=str(tmp_path))) == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
