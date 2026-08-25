#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pytest>=8.0"]
# ///
"""Tests for the research-integrity gate.

`validate_research.py` resolves paths against its own parent directory, so each
case runs it as a subprocess inside a throwaway project. That also tests the
thing that actually matters in practice: the exit code.

Run:  uv run tests/test_validate_research.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parent.parent
VALIDATOR = HARNESS / "scripts" / "validate_research.py"

GOOD_LOG = """# P — research log

## Project summary

A sentence.

### 2026-07-19

* What I did: ran the thing.
* What I expected vs what happened: it worked.
* What this changes about my thinking: nothing yet.
* What I will do next: the next thing.
"""


def project(tmp_path: Path, tree: str, log: str = GOOD_LOG) -> Path:
    (tmp_path / "scripts").mkdir(parents=True, exist_ok=True)
    shutil.copy(VALIDATOR, tmp_path / "scripts" / "validate_research.py")
    (tmp_path / "TREE.md").write_text(tree, encoding="utf-8")
    (tmp_path / "RESEARCH_LOG.md").write_text(log, encoding="utf-8")
    (tmp_path / "results").mkdir(exist_ok=True)
    return tmp_path


def run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/validate_research.py"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


# --- Cases that must PASS ------------------------------------------------


def test_minimal_project_passes(tmp_path: Path) -> None:
    root = project(tmp_path, "- Q1: A question [open]\n")
    result = run(root)
    assert result.returncode == 0, result.stdout


def test_full_chain_with_scorecard_passes(tmp_path: Path) -> None:
    root = project(
        tmp_path,
        "- Q1: A question [open]\n"
        "  - Q1.H1: A hypothesis [supported]\n"
        "    - Q1.H1.E1: An experiment [done] | evidence: results/run.json\n"
        "    - Q1.H1.E1.C1: A claim [survived] | evidence: results/falsify_scorecard.json\n",
    )
    (root / "results/run.json").write_text("{}")
    (root / "results/falsify_scorecard.json").write_text("{}")
    result = run(root)
    assert result.returncode == 0, result.stdout


def test_prose_mentioning_statuses_is_not_parsed_as_nodes(tmp_path: Path) -> None:
    """A tree file has explanatory prose in it; only real nodes are parsed."""
    root = project(
        tmp_path,
        "# Research tree\n\n"
        "Statuses are `open`, `answered`, `abandoned`. Never delete a node.\n\n"
        "- This is a plain bullet, not a node.\n"
        "- Another: with a colon in it.\n\n"
        "- Q1: A question [open]\n",
    )
    result = run(root)
    assert result.returncode == 0, result.stdout


def test_unvalidated_claim_needs_no_evidence(tmp_path: Path) -> None:
    root = project(
        tmp_path,
        "- Q1: A question [open]\n"
        "  - Q1.H1: A hypothesis [open]\n"
        "    - Q1.H1.E1: An experiment [planned]\n"
        "    - Q1.H1.E1.C1: A claim [unvalidated]\n",
    )
    assert run(root).returncode == 0


# --- Cases that must FAIL ------------------------------------------------


@pytest.mark.parametrize(
    ("tree", "expected"),
    [
        ("- Q1: q [open]\n  - Q1.H1: h [open]\n    - Q1.H1.E1: e [done]\n", "requires evidence"),
        ("- Q1: q [open]\n  - Q1.H1: h [bogus]\n", "not in"),
        ("- Q2.H9: orphan [open]\n", "no parent"),
        ("- Q1: q [open]\n  - Q1.H1: h [supported]\n", "no survived/weakened claim"),
        ("- Q1: q [open]\n- Q1: duplicate [open]\n", "duplicate id"),
    ],
)
def test_structural_violations_fail(tmp_path: Path, tree: str, expected: str) -> None:
    result = run(project(tmp_path, tree))
    assert result.returncode == 1
    assert expected in result.stdout


def test_missing_evidence_file_fails(tmp_path: Path) -> None:
    root = project(
        tmp_path,
        "- Q1: q [open]\n  - Q1.H1: h [open]\n"
        "    - Q1.H1.E1: e [done] | evidence: results/absent.json\n",
    )
    result = run(root)
    assert result.returncode == 1
    assert "does not exist" in result.stdout


def test_claim_cannot_graduate_without_scorecard(tmp_path: Path) -> None:
    """The central guarantee: survived requires a falsification artefact."""
    root = project(
        tmp_path,
        "- Q1: q [open]\n  - Q1.H1: h [open]\n"
        "    - Q1.H1.E1: e [done] | evidence: results/run.json\n"
        "    - Q1.H1.E1.C1: c [survived] | evidence: results/run.json\n",
    )
    (root / "results/run.json").write_text("{}")
    result = run(root)
    assert result.returncode == 1
    assert "scorecard" in result.stdout


def test_log_entries_must_be_newest_first(tmp_path: Path) -> None:
    log = (
        GOOD_LOG
        + "\n### 2026-07-20\n\n"
        + "\n".join(
            f"* {q}: x"
            for q in (
                "What I did",
                "What I expected vs what happened",
                "What this changes about my thinking",
                "What I will do next",
            )
        )
    )
    result = run(project(tmp_path, "- Q1: q [open]\n", log))
    assert result.returncode == 1
    assert "newest-first" in result.stdout


def test_log_entry_missing_a_bullet_fails(tmp_path: Path) -> None:
    log = GOOD_LOG.replace("* What I will do next: the next thing.\n", "")
    result = run(project(tmp_path, "- Q1: q [open]\n", log))
    assert result.returncode == 1
    assert "What I will do next" in result.stdout


def test_tree_log_cross_reference_must_resolve(tmp_path: Path) -> None:
    result = run(project(tmp_path, "- Q1: q [open] | log: 2020-01-01\n"))
    assert result.returncode == 1
    assert "no such entry" in result.stdout


# --- Regression tests from adversarial review ---------------------------


def test_bolded_log_bullets_are_accepted(tmp_path: Path) -> None:
    """`* **What I did**: ...` is the natural markdown and used to fail."""
    log = (
        "# P\n\n## Project summary\n\nA sentence.\n\n### 2026-07-19\n\n"
        "* **What I did**: ran the pilot.\n"
        "* **What I expected vs what happened**: expected a gap; saw one.\n"
        "* **What this changes about my thinking**: cue-sensitive.\n"
        "* **What I will do next**: paraphrase.\n"
    )
    assert run(project(tmp_path, "- Q1: q [open]\n", log)).returncode == 0


def test_descriptive_log_header_is_recognised(tmp_path: Path) -> None:
    """A trailing note made the whole entry invisible, not merely unlabelled."""
    log = (
        "# P\n\n## Project summary\n\nA sentence.\n\n### 2026-07-19 — pilot day\n\n"
        "* What I did: ran it.\n* What I expected vs what happened: fine.\n"
        "* What this changes about my thinking: none.\n* What I will do next: more.\n"
    )
    root = project(tmp_path, "- Q1: q [open] | log: 2026-07-19\n", log)
    result = run(root)
    assert result.returncode == 0, result.stdout


def test_fenced_grammar_example_is_not_parsed(tmp_path: Path) -> None:
    """A TREE.md that documents its own grammar is not a duplicate id."""
    tree = (
        "# Research tree\n\nGrammar reminder:\n\n```markdown\n"
        "- Q1: <the project's research question> [open]\n```\n\n"
        "- Q1: Does the detector fire? [open]\n"
    )
    result = run(project(tmp_path, tree))
    assert result.returncode == 0, result.stdout


def test_duplicate_log_dates_are_reported(tmp_path: Path) -> None:
    """Two entries for one date silently discarded a day's content."""
    entry = (
        "* What I did: x\n* What I expected vs what happened: x\n"
        "* What this changes about my thinking: x\n* What I will do next: x\n"
    )
    log = f"# P\n\n## Project summary\n\nS.\n\n### 2026-07-19\n\n{entry}\n### 2026-07-19\n\n{entry}"
    result = run(project(tmp_path, "- Q1: q [open]\n", log))
    assert result.returncode == 1
    assert "duplicate entry" in result.stdout


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
