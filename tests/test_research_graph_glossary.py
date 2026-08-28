#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pytest>=8.0"]
# ///
"""Tests for the record's vocabulary checks and survey.

The split under test is the point of the module: the checks fire only on
facts about terms the author declared, and the survey — which cannot be
reliable — never fails anything.

Run:  uv run tests/test_research_graph_glossary.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parent.parent

from research_graph_glossary import (  # noqa: E402
    glossary_report,
    parse_glossary,
    survey_candidates,
)
from research_graph_model import load  # noqa: E402

TREE = """# Tree

- Q1: Does the record stay readable to someone who has never opened it? [open]
  - Q1.H1: Defining project terms once keeps later nodes readable. [open]
    - Q1.H1.E1: Survey the record for terms used but never defined. [planned]
"""

LOG_HEAD = """# Log

## Project summary

A short summary of the project in plain words.

"""

LOG_TAIL = """---

### 2026-08-24

* What I did: surveyed the record for undefined terms.
* What I expected vs what happened: expected a few, found several.
* What this changes about my thinking: the norm needs a mechanism.
* What I will do next: define the terms the record actually uses.
"""


def project(tmp_path: Path, glossary_body: str = "") -> Path:
    (tmp_path / "TREE.md").write_text(TREE)
    glossary = f"## Glossary\n\n{glossary_body}\n" if glossary_body else ""
    (tmp_path / "RESEARCH_LOG.md").write_text(LOG_HEAD + glossary + LOG_TAIL)
    return tmp_path


def errors(findings: list[str]) -> list[str]:
    return [f for f in findings if f.startswith("ERROR")]


def report(root: Path) -> list[str]:
    return glossary_report(root, load(root))


def test_no_glossary_section_is_silent(tmp_path: Path) -> None:
    """A project with no vocabulary worth defining must raise nothing."""
    assert report(project(tmp_path)) == []


def test_well_formed_glossary_yields_only_a_count(tmp_path: Path) -> None:
    body = (
        "- **Record**: the research tree and the research log taken together.\n"
        "- **Survey**: a report of phrases that may be undefined project terms.\n"
    )
    findings = report(project(tmp_path, body))
    assert not errors(findings)
    assert findings[-1].startswith("INFO") and "2 term(s)" in findings[-1]


def test_empty_definition_is_an_error(tmp_path: Path) -> None:
    """A term listed with no meaning is worse than no entry: the reader looks
    it up and learns nothing."""
    findings = report(project(tmp_path, "- **Record**:\n"))
    assert any("no real definition" in hit for hit in errors(findings))


def test_duplicate_term_is_an_error(tmp_path: Path) -> None:
    body = (
        "- **Record**: the research tree and the research log taken together.\n"
        "- **Record**: something else entirely, contradicting the line above.\n"
    )
    assert any("twice" in hit for hit in errors(report(project(tmp_path, body))))


def test_unused_term_warns_but_does_not_error(tmp_path: Path) -> None:
    """A defined term nothing uses sends the reader hunting for a word the
    record never says."""
    body = "- **Kurtosis ladder**: a scoring scheme this record never mentions again.\n"
    findings = report(project(tmp_path, body))
    assert not errors(findings)
    assert any(f.startswith("WARNING") and "nothing in the tree" in f for f in findings)


def test_survey_drops_ordinary_english(tmp_path: Path) -> None:
    """The false alarms that would make the survey untrustworthy: 'the same
    task' and 'the first sweep' are descriptions, not coined terms."""
    root = project(tmp_path)
    (root / "TREE.md").write_text(
        TREE + "    - Q1.H1.E2: Repeat the same task on the first sweep. [planned]\n"
    )
    phrases = [phrase for phrase, _, _ in survey_candidates(root, load(root))]
    assert "same task" not in phrases
    assert "first sweep" not in phrases


def test_survey_finds_a_real_coinage_and_marks_it_undefined(tmp_path: Path) -> None:
    root = project(tmp_path)
    (root / "TREE.md").write_text(
        TREE + "    - Q1.H1.E2: Run the dictation task against the control arm. [planned]\n"
    )
    rows = {phrase: covered for phrase, _, covered in survey_candidates(root, load(root))}
    assert "dictation task" in rows
    assert rows["dictation task"] is False


def test_survey_marks_a_defined_term_as_covered(tmp_path: Path) -> None:
    body = "- **Dictation task**: a scripted job where an agent records results read out to it.\n"
    root = project(tmp_path, body)
    (root / "TREE.md").write_text(TREE + "    - Q1.H1.E2: Run the dictation task. [planned]\n")
    rows = {phrase: covered for phrase, _, covered in survey_candidates(root, load(root))}
    assert rows.get("dictation task") is True


def test_parenthetical_file_name_stays_with_the_term(tmp_path: Path) -> None:
    """'**Research tree** (`TREE.md`): the state of belief' must read as one
    name and one sentence, not a definition starting with a bracket."""
    body = "- **Research tree** (`TREE.md`): the current state of belief in the project.\n"
    terms = parse_glossary(project(tmp_path, body))
    assert terms[0].term == "Research tree (`TREE.md`)"
    assert terms[0].definition.startswith("the current state")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
