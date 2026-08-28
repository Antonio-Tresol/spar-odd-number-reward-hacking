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


# --- Plain-language tripwire ---------------------------------------------


@pytest.mark.parametrize(
    "node_text",
    [
        "Steering ↑ refusal w/ the Gemma direction",
        "KL spike @ layer 12 → gone after fp32",
        "Probe works b/c prompts leak length",
        "Compare probes & steering on the held-out split",
    ],
)
def test_shorthand_in_node_text_fails(tmp_path: Path, node_text: str) -> None:
    result = run(project(tmp_path, f"- Q1: {node_text} [open]\n"))
    assert result.returncode == 1
    assert "shorthand" in result.stdout


def test_shorthand_in_log_prose_fails(tmp_path: Path) -> None:
    log = GOOD_LOG.replace("ran the thing.", "reran sweep w/ fp32, tl;dr it works.")
    result = run(project(tmp_path, "- Q1: q [open]\n", log))
    assert result.returncode == 1
    assert "shorthand" in result.stdout


def test_plain_prose_with_standard_notation_is_quiet(tmp_path: Path) -> None:
    """Standard notation is not shorthand: slashes in names, percentages, CIs,
    em dashes, 'vs', and inline code (which may contain arrows) all stay quiet."""
    tree = (
        "- Q1: Does the layer-12 direction transfer across A/B prompt splits? [open]\n"
        "  - Q1.H1: Held-out AUC stays within the 95% CI — no paraphrase gap [open]\n"
    )
    log = (
        "# P\n\n## Project summary\n\nParaphrase sensitivity of a linear probe; AUC 0.81 (n=400).\n\n"
        "### 2026-07-19\n\n"
        "* What I did: Reran `scripts/sweep.py --grid coarse->fine` and plotted the scores.\n"
        "* What I expected vs what happened: Expected AUC near 0.75; got 0.81, above the pilot.\n"
        "* What this changes about my thinking: The direction is stronger than assumed.\n"
        "* What I will do next: Run the length-confound regression before touching statuses.\n"
    )
    result = run(project(tmp_path, tree, log))
    assert result.returncode == 0, result.stdout


def test_tree_preamble_prose_and_arrows_are_allowed(tmp_path: Path) -> None:
    """The template's own preamble — prose, an arrow chain naming the hierarchy,
    a fenced grammar example — sits before the first node and is not policed."""
    tree = (
        "# Research tree\n\n"
        "State of the project: questions → hypotheses → experiments → claims.\n\n"
        "```markdown\n- Q1: <question> [open]\n```\n\n"
        "- Q1: Does the detector fire? [open]\n"
    )
    result = run(project(tmp_path, tree))
    assert result.returncode == 0, result.stdout


def test_prose_after_first_node_fails(tmp_path: Path) -> None:
    """Freeform sections in the tree are state hiding outside the grammar."""
    tree = "- Q1: A question [open]\n\n## Session notes\n\nNarrative that belongs in the log.\n"
    result = run(project(tmp_path, tree))
    assert result.returncode == 1
    assert "non-node line" in result.stdout


def test_fenced_block_after_nodes_is_allowed(tmp_path: Path) -> None:
    """Fenced content is exempt everywhere: a grammar example below the nodes
    is quoted material, not freeform state."""
    tree = "- Q1: q [open]\n\n```markdown\nexample: not → parsed\n```\n"
    result = run(project(tmp_path, tree))
    assert result.returncode == 0, result.stdout


def test_node_hidden_in_a_fence_among_the_nodes_fails(tmp_path: Path) -> None:
    """A fenced node reads as recorded but is checked by nothing.

    Found by a red-team run told to graduate a claim by any means: it wrapped
    the claim in a code fence, which every check skips. The line still says
    [survived] to anyone opening the file, while the scorecard gate, the
    evidence rule, the length limit, and the shorthand tripwire all see
    nothing — the validator counted one node fewer and exited 0.
    """
    tree = (
        "- Q1: Does the detector fire? [open]\n"
        "  - Q1.H1: It fires on cued prompts. [open]\n"
        "```\n"
        "    - Q1.H1.C1: The detector fires above baseline. [survived]\n"
        "```\n"
    )
    result = run(project(tmp_path, tree))
    assert result.returncode == 1
    assert "inside a fenced block" in result.stdout


def test_fenced_grammar_example_in_the_preamble_is_quiet(tmp_path: Path) -> None:
    """The carve-out the rule above deliberately keeps.

    A fenced example above the first node is documentation — the template's
    own preamble carries one — and a reader never mistakes it for the tree.
    Policing it would fire on every project the installer creates.
    """
    tree = (
        "# Research tree\n\n"
        "Grammar, by example:\n\n"
        "```markdown\n- Q1.H1.E1.C1: A claim sentence. [survived]\n```\n\n"
        "- Q1: Does the detector fire? [open]\n"
    )
    result = run(project(tmp_path, tree))
    assert result.returncode == 0, result.stdout


# --- Altitude and grammar-drift tripwires --------------------------------


def test_structured_claim_at_realistic_length_is_quiet(tmp_path: Path) -> None:
    """The claim shape that survived a real project's hand clean-up — one
    falsifiable sentence plus Support and Falsification clauses, ~800
    characters — must pass the length gate comfortably."""
    claim = (
        "The assistant axis is stable under subsampling of the roles. — Support: "
        "axes built from two random halves of the 80 roles agree at cosine 0.966 "
        "(95% interval 0.947-0.978, 200 half-samples, layer 30); rebuilding the "
        "vector set with a different random seed reproduces the axis at cosine "
        "0.991, and dropping any single role family moves it by at most 0.8 "
        "degrees; n=200 resamples throughout, mean over three rollouts per role. "
        "— Falsification: a permutation test shuffling role labels destroys the "
        "agreement (95th percentile 0.31), and the axis is unchanged when the "
        "prompt template is paraphrased, so the stability is not a template "
        "artefact; verdict survived, single model family caveat recorded"
    )
    tree = (
        "- Q1: A question [open]\n"
        "  - Q1.H1: A hypothesis [open]\n"
        "    - Q1.H1.E1: An experiment [done] | evidence: results/run.json\n"
        f"    - Q1.H1.E1.C1: {claim} [unvalidated]\n"
    )
    root = project(tmp_path, tree)
    (root / "results/run.json").write_text("{}")
    result = run(root)
    assert result.returncode == 0, result.stdout


def test_essay_node_fails_the_length_gate(tmp_path: Path) -> None:
    """A protocol inlined into a node (the dominant real-world failure,
    4,000-12,000 characters observed) trips the altitude check."""
    protocol = "The registered read compares matched windows across layers. " * 30
    result = run(project(tmp_path, f"- Q1: {protocol.strip()} [open]\n"))
    assert result.returncode == 1
    assert "headline" in result.stdout


def test_ghost_node_id_is_named(tmp_path: Path) -> None:
    """Sub-lettered ids (E4b, seen in a real tree) previously fell out of
    validation silently; now they are rejected by name."""
    tree = (
        "- Q1: A question [open]\n"
        "  - Q1.H1: A hypothesis [open]\n"
        "    - Q1.H1.E4b: an experiment the validator never saw [done]\n"
    )
    result = run(project(tmp_path, tree))
    assert result.returncode == 1
    assert "not a valid node id" in result.stdout


def test_malformed_log_header_is_reported(tmp_path: Path) -> None:
    """A typo'd date used to silently drop the entry from validation."""
    log = GOOD_LOG + "\n### 2026-7-2\n\n* What I did: vanished from validation.\n"
    result = run(project(tmp_path, "- Q1: q [open]\n", log))
    assert result.returncode == 1
    assert "dated entry header" in result.stdout


def test_fenced_header_placeholder_is_quiet(tmp_path: Path) -> None:
    """The template documents its entry format as '### YYYY-MM-DD' inside a
    fence; fenced examples are exempt everywhere."""
    log = (
        "# P\n\n## Project summary\n\nA sentence.\n\n"
        "Entry format:\n\n```\n### YYYY-MM-DD\n\n* What I did:\n```\n\n"
        "### 2026-07-19\n\n"
        "* What I did: ran the thing.\n* What I expected vs what happened: fine.\n"
        "* What this changes about my thinking: nothing.\n* What I will do next: more.\n"
    )
    result = run(project(tmp_path, "- Q1: q [open]\n", log))
    assert result.returncode == 0, result.stdout


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
