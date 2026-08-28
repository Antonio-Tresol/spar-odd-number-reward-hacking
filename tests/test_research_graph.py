#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pytest>=8.0"]
# ///
"""Tests for the research-record graph layer (research_graph_model.py,
research_graph_checks.py, research_graph_write.py).

Everything here is checked against the binding build spec, not against any
implementation detail the spec does not promise. `build_fixture_project`
builds the one golden project the rest of the file trusts;
`test_fixture_project_passes_the_real_validator` proves it is itself a
valid record, by running the real validator against it, before anything
else here relies on it.

Two things are tested for each check, and the second matters more: that it
FIRES on the thing it is meant to catch, and that it stays QUIET on the
realistic case it should not touch.

Run:  uv run --python 3.13 --with pytest pytest tests/test_research_graph.py -q
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parent.parent
VALIDATOR = HARNESS / "scripts" / "validate_research.py"
META = Path("/home/user/research-harness-meta")
GEMMA = Path("/home/user/antonio-tresol/gemma4-emotion-vectors")

from research_graph_checks import (  # noqa: E402
    compute_pin,
    drift_report,
    orphan_report,
    read_pins,
    verify,
)
from research_graph_model import IR_VERSION, evidence_kind, load, to_ir, to_mermaid  # noqa: E402
from research_graph_write import (  # noqa: E402
    add_evidence,
    add_node,
    add_note,
    append_log_entry,
    set_status,
    set_text,
)

# --- Golden fixture content ------------------------------------------------
# Two questions, nested hypotheses/experiments/claims, one claim pinned for
# provenance (Q1.H1.E1.C1), one graduated but never pinned (Q1.H1.E1.C3, so
# drift_report's "no pin stays quiet" branch has something real to check),
# a linked note, an orphan note, and the results files the evidence points at.

TREE_MD = """# Probe helpfulness detection research tree

- Q1: Does a linear probe trained on hidden activations predict whether a generated response will be rated helpful by a held-out grader? [open] | log: 2026-08-22
  - Q1.H1: Probe accuracy on held-out prompts clears a majority-class baseline by a wide margin [supported] | log: 2026-08-20
    - Q1.H1.E1: Train a logistic regression probe on layer 14 activations from 800 labelled responses and evaluate on a held-out split [done] | evidence: results/run.json, notes/linked-note.md
      - Q1.H1.E1.C1: The probe reaches 0.86 accuracy on the held-out split against a 0.52 majority-class baseline, and the gap survives a label-permutation control [survived] | evidence: results/run.json, results/falsify_scorecard.json
      - Q1.H1.E1.C2: The probe may be reading response length rather than helpfulness, based on an unfinished correlation check [unvalidated]
      - Q1.H1.E1.C3: The accuracy gap disappears once responses are matched for length, so the probe was mostly a length detector [failed] | evidence: results/run.json, results/second_scorecard.json
    - Q1.H1.E2: Repeat the probe training on layer 20 activations to check whether the effect is specific to one layer [planned]
- Q2: Does the "held-out" prompt split leak information the model could have seen during training? [open]
  - Q2.H1: Held-out prompts share no exact substrings with the training prompts [open]
    - Q2.H1.E1: Run an exact-substring overlap scan between the held-out and training prompt sets [running]
"""

RESEARCH_LOG_MD = """# Probe helpfulness detection research log

## Project summary

This project asks whether a lightweight linear probe on hidden activations can predict whether a generated response will be rated helpful by a held-out grader, and whether any such signal is layer-specific or is instead reading a confound such as response length.

### 2026-08-22

* What I did: Trained the probe described in Q1.H1.E1 on layer 14 activations and wrote the run summary to results/run.json.
* What I expected vs what happened: Expected accuracy near the 0.75 pilot estimate; observed 0.86 against a 0.52 majority-class baseline.
* What this changes about my thinking: The signal looks stronger than the pilot suggested, so the length confound check now matters more.
* What I will do next: Run the label permutation control and check whether the probe reads response length instead of helpfulness.

### 2026-08-20

* What I did: Scoped the research question and registered the training protocol as a linked note before running anything.
* What I expected vs what happened: Setup went as planned; no results yet.
* What this changes about my thinking: Nothing yet, this is the starting point for the project.
* What I will do next: Collect the labelled response set and train the first probe.
"""

RUN_JSON = '{"probe_accuracy": 0.86, "baseline_accuracy": 0.52, "n_responses": 800, "layer": 14}'
FALSIFY_SCORECARD_JSON = (
    '{"claim": "Q1.H1.E1.C1", "permutation_p": 0.01, "n_permutations": 1000, "verdict": "survived"}'
)
SECOND_SCORECARD_JSON = '{"claim": "Q1.H1.E1.C3", "length_matched_gap": 0.01, "verdict": "failed"}'

LINKED_NOTE_MD = """# Layer 14 probe training protocol

Dated 2026-08-19. Registered before training the first probe, linked as evidence from Q1.H1.E1.

## Protocol

Train a logistic regression probe on layer 14 residual stream activations from 800 labelled responses, an 80/20 held-out split, and report accuracy against a majority-class baseline.
"""

ORPHAN_NOTE_MD = """# Scratch ideas for later probes

Dated 2026-08-18. Unlinked scratch notes; nothing here has been registered against a node yet.

## Ideas

Try a probe on the residual stream at multiple layers at once, and compare it against a probe trained on attention patterns instead of hidden states.
"""


def write(root: Path, relative: str, text: str) -> Path:
    """Write `text` to `root/relative`, creating parent directories."""
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def run_validator(root: Path) -> subprocess.CompletedProcess[str]:
    """Run the project's own copy of the validator, exactly as a fresh clone would."""
    return subprocess.run(
        [sys.executable, "scripts/validate_research.py"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def build_fixture_project(tmp_path: Path) -> Path:
    """Build a complete, realistic research-record project under tmp_path.

    Every write and check module resolves the sibling validator as
    `root / "scripts" / "validate_research.py"` (validate_research.py computes
    its own root from its own file location, not from cwd), so the validator
    is copied in here exactly as a real consuming project would carry its own
    copy — this is what makes verify() and the write commands' rollback checks
    validate THIS project instead of the harness worktree.
    """
    (tmp_path / "scripts").mkdir(parents=True, exist_ok=True)
    shutil.copy(VALIDATOR, tmp_path / "scripts" / "validate_research.py")
    write(tmp_path, "TREE.md", TREE_MD)
    write(tmp_path, "RESEARCH_LOG.md", RESEARCH_LOG_MD)
    write(tmp_path, "results/run.json", RUN_JSON)
    write(tmp_path, "results/falsify_scorecard.json", FALSIFY_SCORECARD_JSON)
    write(tmp_path, "results/second_scorecard.json", SECOND_SCORECARD_JSON)
    write(tmp_path, "notes/linked-note.md", LINKED_NOTE_MD)
    write(tmp_path, "notes/scratch-ideas.md", ORPHAN_NOTE_MD)
    return tmp_path


def embed_pin(root: Path, scorecard_relpath: str, pin: dict[str, object]) -> None:
    """Write `pin` under the "provenance" key of a scorecard file on disk."""
    path = root / scorecard_relpath
    data = json.loads(path.read_text())
    data["provenance"] = pin
    path.write_text(json.dumps(data), encoding="utf-8")


# --- The fixture itself must be a valid record ------------------------------


def test_fixture_project_passes_the_real_validator(tmp_path: Path) -> None:
    """The golden fixture the rest of this file trusts is a valid record."""
    result = run_validator(build_fixture_project(tmp_path))
    assert result.returncode == 0, result.stdout


# --- Model: load(), evidence kinds, artifacts, documents, log entries ------


def test_load_parses_node_fields_and_wiring(tmp_path: Path) -> None:
    """Every stored field is readable and parent/children are wired both ways."""
    graph = load(build_fixture_project(tmp_path))
    assert set(graph.nodes) == {
        "Q1",
        "Q1.H1",
        "Q1.H1.E1",
        "Q1.H1.E1.C1",
        "Q1.H1.E1.C2",
        "Q1.H1.E1.C3",
        "Q1.H1.E2",
        "Q2",
        "Q2.H1",
        "Q2.H1.E1",
    }
    c1 = graph.nodes["Q1.H1.E1.C1"]
    assert (c1.node_type, c1.status, c1.parent) == ("claim", "survived", "Q1.H1.E1")
    assert set(c1.evidence) == {"results/run.json", "results/falsify_scorecard.json"}
    assert c1.children == ()
    q1 = graph.nodes["Q1"]
    assert q1.node_type == "question"
    assert q1.parent is None
    assert q1.log_date == "2026-08-22"
    assert set(graph.nodes["Q1.H1.E1"].children) == {
        "Q1.H1.E1.C1",
        "Q1.H1.E1.C2",
        "Q1.H1.E1.C3",
    }


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("notes/plan.md", "note"),
        ("notes/sub/plan.md", "note"),
        ("references/paper.bib", "paper"),
        ("data/papers/foo.pdf", "paper"),  # data/papers/ beats the later data/ -> dataset rule
        ("some/dir/citation.bib", "paper"),
        ("results/interview_transcript.txt", "trace"),  # "transcript" beats results/ -> result
        ("logs/session.log", "trace"),
        ("archive/run.tar.gz", "trace"),
        ("scripts/analyze.py", "code"),
        ("src/lib/model.py", "code"),
        ("notebooks/explore.py", "code"),  # *.py alone, no scripts/ or src/ prefix
        ("data/raw/dataset.csv", "dataset"),  # data/ beats the later *.csv -> result rule
        ("results/summary.json", "result"),
        ("eval_metrics.csv", "result"),  # *.csv alone, no directory prefix
        ("README.md", "other"),
        ("notes_appendix.txt", "other"),  # "notes" without the slash is not the notes/ rule
    ],
)
def test_evidence_kind_inference(path: str, expected: str) -> None:
    assert evidence_kind(path) == expected


def test_artifacts_record_existence_and_referenced_by(tmp_path: Path) -> None:
    """Every evidence path becomes one artifact, deduplicated across nodes."""
    root = build_fixture_project(tmp_path)
    run_artifact = load(root).artifacts["results/run.json"]
    assert run_artifact.kind == "result"
    assert run_artifact.exists is True
    assert set(run_artifact.referenced_by) == {"Q1.H1.E1", "Q1.H1.E1.C1", "Q1.H1.E1.C3"}
    (root / "results/run.json").unlink()
    assert load(root).artifacts["results/run.json"].exists is False


def test_documents_and_log_entries_capture_mentions_and_orphans(tmp_path: Path) -> None:
    """The linked note is findable from its node; the untouched note is the
    lone orphan; log-entry mentions surface the ids and paths in prose."""
    graph = load(build_fixture_project(tmp_path))
    linked = graph.documents["notes/linked-note.md"]
    assert linked.title == "Layer 14 probe training protocol"
    assert linked.linked_from == ("Q1.H1.E1",)
    assert linked.orphan is False
    orphan_paths = {path for path, doc in graph.documents.items() if doc.orphan}
    assert orphan_paths == {"notes/scratch-ideas.md"}
    entry = graph.entries["2026-08-22"]
    assert "Q1.H1.E1" in entry.mentions_ids
    assert "results/run.json" in entry.mentions_paths


# --- Model: JSON IR and mermaid ---------------------------------------------


def test_to_ir_schema_and_determinism(tmp_path: Path) -> None:
    """The IR has the documented shape, is JSON-serialisable, sorted, and
    identical across two independent loads of the same record."""
    root = build_fixture_project(tmp_path)
    ir1 = to_ir(load(root))
    ir2 = to_ir(load(root))
    assert ir1 == ir2
    assert json.dumps(ir1)  # serialisable without raising
    assert ir1["version"] == IR_VERSION == 1
    assert set(ir1) == {"version", "root", "nodes", "entries", "documents", "artifacts"}
    node = next(n for n in ir1["nodes"] if n["id"] == "Q1.H1.E1.C1")
    assert set(node) == {"id", "type", "text", "status", "evidence", "log", "parent", "children"}
    assert (node["type"], node["status"], node["log"]) == ("claim", "survived", None)
    assert set(ir1["entries"][0]) == {"date", "mentions"}
    assert set(ir1["entries"][0]["mentions"]) == {"ids", "paths"}
    doc = next(d for d in ir1["documents"] if d["path"] == "notes/linked-note.md")
    assert set(doc) == {"path", "title", "linked_from", "orphan", "mentions"}
    art = next(a for a in ir1["artifacts"] if a["path"] == "results/run.json")
    assert set(art) == {"path", "kind", "exists", "referenced_by"}
    assert [n["id"] for n in ir1["nodes"]] == sorted(n["id"] for n in ir1["nodes"])
    assert [e["date"] for e in ir1["entries"]] == ["2026-08-22", "2026-08-20"]
    assert [d["path"] for d in ir1["documents"]] == sorted(d["path"] for d in ir1["documents"])
    assert [a["path"] for a in ir1["artifacts"]] == sorted(a["path"] for a in ir1["artifacts"])


def test_mermaid_contains_ids_escapes_quotes_and_evidence_edges(tmp_path: Path) -> None:
    """Every node id appears, a quoted node text cannot break a label, and
    evidence edges only appear when with_evidence=True."""
    graph = load(build_fixture_project(tmp_path))
    plain = to_mermaid(graph)
    assert plain.startswith("flowchart TD")
    for node_id in graph.nodes:
        assert node_id in plain
    assert '"held-out"' not in plain  # the raw quote pair in Q2's text must be escaped
    assert "held-out" in plain  # but the word itself survives
    assert "results/run.json" not in plain
    assert "results/run.json" in to_mermaid(graph, with_evidence=True)


# --- Checks: orphans ---------------------------------------------------------


def test_orphan_report_fires_on_the_orphan_note(tmp_path: Path) -> None:
    findings = orphan_report(load(build_fixture_project(tmp_path)))
    assert len(findings) == 1
    assert "notes/scratch-ideas.md" in findings[0]


def test_orphan_report_quiet_when_no_orphans(tmp_path: Path) -> None:
    """Deleting the never-linked note leaves nothing unreferenced to report."""
    root = build_fixture_project(tmp_path)
    (root / "notes/scratch-ideas.md").unlink()
    assert orphan_report(load(root)) == []


# --- Checks: provenance pin --------------------------------------------------


def test_compute_pin_hashes_and_excludes_scorecards(tmp_path: Path) -> None:
    root = build_fixture_project(tmp_path)
    pin = compute_pin(root, ["Q1.H1.E1.C1"])
    assert pin["pinned_at"] == date.today().isoformat()
    assert pin["git_commit"] == "no-git"
    expected = hashlib.sha256((root / "results/run.json").read_bytes()).hexdigest()
    assert pin["evidence_sha256"]["results/run.json"] == expected
    assert "results/falsify_scorecard.json" not in pin["evidence_sha256"]


def test_compute_pin_reports_missing_evidence_as_missing(tmp_path: Path) -> None:
    root = build_fixture_project(tmp_path)
    (root / "results/run.json").unlink()
    pin = compute_pin(root, ["Q1.H1.E1.C1"])
    assert pin["evidence_sha256"]["results/run.json"] == "missing"


def test_read_pins_finds_embedded_provenance_only_for_pinned_claims(tmp_path: Path) -> None:
    root = build_fixture_project(tmp_path)
    pin = compute_pin(root, ["Q1.H1.E1.C1"])
    embed_pin(root, "results/falsify_scorecard.json", pin)
    pins = read_pins(root, load(root))
    assert pins["Q1.H1.E1.C1"]["evidence_sha256"] == pin["evidence_sha256"]
    assert "Q1.H1.E1.C3" not in pins  # graduated, has a scorecard, but never pinned


# --- Checks: drift, the fire/quiet/no-pin trio ------------------------------


def test_drift_report_quiet_when_pinned_evidence_unchanged(tmp_path: Path) -> None:
    root = build_fixture_project(tmp_path)
    embed_pin(root, "results/falsify_scorecard.json", compute_pin(root, ["Q1.H1.E1.C1"]))
    assert drift_report(root, load(root)) == []


@pytest.mark.parametrize("wipe", [False, True])
def test_drift_report_fires_on_a_changed_or_missing_pinned_file(tmp_path: Path, wipe: bool) -> None:
    root = build_fixture_project(tmp_path)
    embed_pin(root, "results/falsify_scorecard.json", compute_pin(root, ["Q1.H1.E1.C1"]))
    target = root / "results/run.json"
    if wipe:
        target.unlink()
    else:
        target.write_text(target.read_text() + "\nmutated\n")
    findings = drift_report(root, load(root))
    assert len(findings) == 1
    assert "Q1.H1.E1.C1" in findings[0]
    assert "results/run.json" in findings[0]


def test_drift_report_quiet_when_claim_has_no_pin(tmp_path: Path) -> None:
    """Precision over recall: a graduated claim nobody pinned stays quiet
    even after its evidence changes, so legacy records do not get noisy."""
    root = build_fixture_project(tmp_path)
    (root / "results/run.json").write_text('{"probe_accuracy": 0.99}')
    assert drift_report(root, load(root)) == []


# --- Checks: verify exit codes ----------------------------------------------


def test_verify_exit_code_zero_on_clean_fixture(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The fixture has an orphan note and an unpinned graduated claim by
    default; both are warning/info only, so a clean record still verifies."""
    assert verify(build_fixture_project(tmp_path)) == 0
    assert "OK" in capsys.readouterr().out


def test_verify_exit_code_one_on_missing_evidence(tmp_path: Path) -> None:
    root = build_fixture_project(tmp_path)
    (root / "results/run.json").unlink()
    assert verify(root) == 1


def test_verify_exit_code_one_on_drift(tmp_path: Path) -> None:
    root = build_fixture_project(tmp_path)
    embed_pin(root, "results/falsify_scorecard.json", compute_pin(root, ["Q1.H1.E1.C1"]))
    (root / "results/run.json").write_text('{"probe_accuracy": 0.99}')
    assert verify(root) == 1


def test_verify_exit_code_one_on_fabricated_verification_quote(tmp_path: Path) -> None:
    """The verification checks ride inside verify: a scorecard whose quoted
    excerpt does not appear in the file it cites fails the whole record."""
    root = build_fixture_project(tmp_path)
    scorecard = root / "results/falsify_scorecard.json"
    data = json.loads(scorecard.read_text())
    data["verification"] = {
        "method": "trace-read",
        "inputs": ["results/run.json"],
        "verdict": "survives",
        "runs": [
            {
                "reader": "reader-model",
                "at": "2026-08-24",
                "verdict": "survives",
                "quotes": [
                    {
                        "path": "results/run.json",
                        "excerpt": "a sentence that appears nowhere in that file",
                    }
                ],
            }
        ],
    }
    scorecard.write_text(json.dumps(data))
    assert verify(root) == 1


def test_set_text_rewrites_only_the_text(tmp_path: Path) -> None:
    """The gap this command fills: change the headline, keep everything else.

    Two measured sessions read the source to confirm no such command existed
    and fell back to hand edits; one of those hand edits introduced a log
    reference to an entry that did not exist yet. Status, evidence, and the
    log date must survive untouched.
    """
    root = build_fixture_project(tmp_path)
    exit_code = set_text(root, "Q1.H1.E1", "Train a probe on layer 14 and evaluate held out.")
    assert exit_code == 0
    line = next(
        line
        for line in (root / "TREE.md").read_text().splitlines()
        if line.strip().startswith("- Q1.H1.E1:")
    )
    assert "Train a probe on layer 14 and evaluate held out. [done]" in line
    assert "evidence: results/run.json, notes/linked-note.md" in line


def test_set_text_trims_an_over_long_node_to_a_headline(tmp_path: Path) -> None:
    """The altitude workflow end to end: a node past the length gate is
    rejected until its text becomes a headline, and set-text is what does it."""
    root = build_fixture_project(tmp_path)
    tree = (root / "TREE.md").read_text()
    bloated = tree.replace(
        "Repeat the probe training on layer 20 activations to check whether the "
        "effect is specific to one layer",
        "Repeat the probe training on layer 20. " + ("Protocol detail. " * 90),
    )
    (root / "TREE.md").write_text(bloated, encoding="utf-8")
    assert run_validator(root).returncode == 1
    assert set_text(root, "Q1.H1.E2", "Repeat the probe training on layer 20 activations.") == 0
    assert run_validator(root).returncode == 0


def test_set_text_refuses_empty_text_and_unknown_node(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = build_fixture_project(tmp_path)
    before = (root / "TREE.md").read_bytes()
    assert set_text(root, "Q1.H1.E1", "   ") == 1
    assert "is empty" in capsys.readouterr().out
    assert set_text(root, "Q9.H9", "Some text.") == 1
    assert "no node called Q9.H9" in capsys.readouterr().out
    assert (root / "TREE.md").read_bytes() == before


def test_set_text_rejects_text_that_would_break_the_record(tmp_path: Path) -> None:
    """set-text is a write like any other: the shorthand tripwire still applies
    and the file comes back byte-identical."""
    root = build_fixture_project(tmp_path)
    before = (root / "TREE.md").read_bytes()
    assert set_text(root, "Q1.H1.E1", "Probe trained w/o the length control.") == 1
    assert (root / "TREE.md").read_bytes() == before


# --- Write: add_node ---------------------------------------------------------


def test_add_node_refuses_non_unvalidated_status_for_new_claim(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = build_fixture_project(tmp_path)
    before = (root / "TREE.md").read_bytes()
    exit_code = add_node(root, "Q1.H1.E1", "claim", "A new claim about the probe.", "survived", [])
    assert exit_code == 1
    assert (root / "TREE.md").read_bytes() == before
    assert "unvalidated" in capsys.readouterr().out


def test_add_node_inserts_after_parents_last_descendant(tmp_path: Path) -> None:
    """New children are numbered max+1 and land right after the parent's
    last existing descendant, indented two spaces deeper than the parent."""
    root = build_fixture_project(tmp_path)
    text = "A fresh plain-language claim about the probe results."
    assert add_node(root, "Q1.H1.E1", "claim", text, None, []) == 0
    lines = (root / "TREE.md").read_text().splitlines()
    new_i = next(i for i, line in enumerate(lines) if line.strip().startswith("- Q1.H1.E1.C4:"))
    last_sibling_i = next(i for i, line in enumerate(lines) if "Q1.H1.E1.C3:" in line)
    next_uncle_i = next(i for i, line in enumerate(lines) if "Q1.H1.E2:" in line)
    parent_line = next(line for line in lines if "Q1.H1.E1:" in line)
    parent_indent = len(parent_line) - len(parent_line.lstrip(" "))
    assert last_sibling_i < new_i < next_uncle_i
    assert lines[new_i].startswith(" " * (parent_indent + 2) + "- ")
    assert "[unvalidated]" in lines[new_i]


def test_write_rollback_restores_file_byte_identical_on_invalid_write(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The central guarantee: a write that would break the record leaves the
    file exactly as it was, byte for byte, not merely textually similar."""
    root = build_fixture_project(tmp_path)
    before = (root / "TREE.md").read_bytes()
    bad_text = "A hypothesis written w/o full words."
    exit_code = add_node(root, "Q1", "hypothesis", bad_text, None, [])
    assert exit_code == 1
    assert (root / "TREE.md").read_bytes() == before
    out = capsys.readouterr().out
    assert "Rejected — the record would become invalid; nothing was written:" in out


def test_dry_run_reports_a_write_that_would_be_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A dry run must rehearse the write, not just print it.

    Two measured runs saw a clean preview and then a hard rejection from the
    identical command a moment later, because the preview never ran the
    validator. A preview that says "this will work" and is wrong is worse than
    no preview: it spends the author's trust before spending their time.
    """
    root = build_fixture_project(tmp_path)
    before = (root / "TREE.md").read_bytes()
    exit_code = add_node(
        root, "Q1", "hypothesis", "A hypothesis written w/o full words.", None, [], dry_run=True
    )
    assert exit_code == 1
    assert (root / "TREE.md").read_bytes() == before, "a dry run must never leave a change behind"
    out = capsys.readouterr().out
    assert "Dry run — nothing was written" in out
    assert "would be REJECTED" in out


def test_dry_run_confirms_a_write_that_would_be_accepted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The other half of the contract: a valid write previews as valid and
    still writes nothing."""
    root = build_fixture_project(tmp_path)
    before = (root / "TREE.md").read_bytes()
    exit_code = add_node(
        root, "Q1", "hypothesis", "Probe accuracy holds on a second layer.", None, [], dry_run=True
    )
    assert exit_code == 0
    assert (root / "TREE.md").read_bytes() == before
    out = capsys.readouterr().out
    assert "would still be valid" in out


def test_rejection_says_when_the_record_was_already_invalid(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A refusal caused by a pre-existing violation must say so.

    An over-long node already in the tree makes every write fail, including
    the relocation write that would fix it. Without this note the refusal
    reads as "your command was wrong": one measured run abandoned the writing
    commands entirely after exactly that misreading.
    """
    root = build_fixture_project(tmp_path)
    tree = (root / "TREE.md").read_text()
    bloated = tree.replace(
        "Repeat the probe training on layer 20 activations to check whether the "
        "effect is specific to one layer",
        "Repeat the probe training on layer 20. " + ("Protocol detail. " * 90),
    )
    (root / "TREE.md").write_text(bloated, encoding="utf-8")
    exit_code = add_note(root, "protocol", "Protocol", "The relocated protocol text.", "Q1.H1.E2")
    assert exit_code == 1
    out = capsys.readouterr().out
    assert "ALREADY invalid before this command ran" in out
    assert not (root / "notes/protocol.md").exists()


@pytest.mark.parametrize("joined", ["results/a.json,results/b.json", "results/a.json,"])
def test_comma_joined_evidence_path_is_refused_by_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], joined: str
) -> None:
    """Evidence is stored comma-separated, so a comma inside one path splits it
    into two paths that do not exist. Authors reach for the joined form because
    the record's own format looks like a list; the refusal names the fix."""
    root = build_fixture_project(tmp_path)
    before = (root / "TREE.md").read_bytes()
    exit_code = add_evidence(root, "Q1.H1.E2", [joined])
    assert exit_code == 1
    assert (root / "TREE.md").read_bytes() == before
    out = capsys.readouterr().out
    assert "contains a comma" in out
    assert "separated by spaces" in out


def test_add_note_link_rolls_back_both_files_on_invalid_result(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A rejected add-note removes the note file it just wrote too: the
    transaction covers every file the command touched, not only TREE.md.
    A comma in the slug makes the evidence line split into two fabricated,
    non-existent paths, which the validator rejects."""
    root = build_fixture_project(tmp_path)
    before = (root / "TREE.md").read_bytes()
    exit_code = add_note(root, "draft,v2", "Draft note", "A short draft paragraph.", "Q1.H1.E2")
    assert exit_code == 1
    assert (root / "TREE.md").read_bytes() == before
    assert not (root / "notes/draft,v2.md").exists()
    assert "Rejected" in capsys.readouterr().out


# --- Write: set_status --------------------------------------------------------


def test_set_status_refuses_graduation_without_scorecard(tmp_path: Path) -> None:
    root = build_fixture_project(tmp_path)
    before = (root / "TREE.md").read_bytes()
    exit_code = set_status(root, "Q1.H1.E1.C2", "survived", ["results/run.json"], None)
    assert exit_code == 1
    assert (root / "TREE.md").read_bytes() == before


def test_set_status_graduates_claim_with_scorecard_evidence(tmp_path: Path) -> None:
    root = build_fixture_project(tmp_path)
    write(root, "results/c2_scorecard.json", '{"claim": "Q1.H1.E1.C2", "verdict": "survived"}')
    evidence = ["results/run.json", "results/c2_scorecard.json"]
    assert set_status(root, "Q1.H1.E1.C2", "survived", evidence, None) == 0
    text = (root / "TREE.md").read_text()
    assert "Q1.H1.E1.C2: " in text and "[survived]" in text
    assert "results/c2_scorecard.json" in text


# --- Write: append_log_entry and add_note ------------------------------------


def test_append_log_entry_merges_into_existing_date(tmp_path: Path) -> None:
    root = build_fixture_project(tmp_path)
    exit_code = append_log_entry(
        root,
        "2026-08-22",
        "Reran the analysis with a fixed random seed.",
        "Expected the same number; a data ordering bug changed it slightly.",
        "The pipeline needs a stable sort before hashing.",
        "Add the stable sort and rerun the probe training.",
    )
    assert exit_code == 0
    text = (root / "RESEARCH_LOG.md").read_text()
    assert text.count("### 2026-08-22") == 1
    assert "Reran the analysis with a fixed random seed." in text
    assert "Trained the probe described in Q1.H1.E1" in text


def test_append_log_entry_refuses_a_date_older_than_the_newest_entry(tmp_path: Path) -> None:
    root = build_fixture_project(tmp_path)
    before = (root / "RESEARCH_LOG.md").read_bytes()
    exit_code = append_log_entry(
        root, "2020-01-01", "Did the thing.", "As planned.", "Nothing.", "More."
    )
    assert exit_code == 1
    assert (root / "RESEARCH_LOG.md").read_bytes() == before


def test_add_note_creates_file_and_links_evidence(tmp_path: Path) -> None:
    root = build_fixture_project(tmp_path)
    body = "A short plan for repeating the probe training on layer 20 activations."
    exit_code = add_note(root, "layer-20-followup", "Layer 20 follow-up plan", body, "Q1.H1.E2")
    assert exit_code == 0
    note_text = (root / "notes/layer-20-followup.md").read_text()
    assert note_text.startswith("# Layer 20 follow-up plan")
    assert f"Dated {date.today().isoformat()}." in note_text
    assert "notes/layer-20-followup.md" in (root / "TREE.md").read_text()


def test_add_node_dry_run_writes_nothing_and_previews_the_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--dry-run is a contract every write command shares through one
    transaction helper, so exercising it once here covers all five."""
    root = build_fixture_project(tmp_path)
    before = (root / "TREE.md").read_bytes()
    text = "Preview only, not written."
    exit_code = add_node(root, "Q1.H1", "experiment", text, None, [], dry_run=True)
    assert exit_code == 0
    assert (root / "TREE.md").read_bytes() == before
    assert f"- Q1.H1.E3: {text} [planned]" in capsys.readouterr().out


def test_add_evidence_unions_with_existing_paths(tmp_path: Path) -> None:
    """A regression that replaced instead of unioned would silently drop
    every already-recorded evidence path on the node's next status change."""
    root = build_fixture_project(tmp_path)
    write(root, "results/extra.json", '{"note": "additional evidence"}')
    assert add_evidence(root, "Q1.H1.E1", ["results/extra.json"]) == 0
    line = next(line for line in (root / "TREE.md").read_text().splitlines() if "Q1.H1.E1:" in line)
    assert line.rstrip().endswith(
        "evidence: results/run.json, notes/linked-note.md, results/extra.json"
    )


# --- False-positive suite: real projects, read-only -------------------------


@pytest.mark.skipif(not META.exists(), reason="research-harness-meta is not checked out here")
def test_research_harness_meta_loads_clean_with_no_drift() -> None:
    """load, orphan_report, and drift_report must all run without raising on
    a real project, and drift must stay quiet (legacy claims are unpinned)."""
    graph = load(META)
    orphan_report(graph)
    assert drift_report(META, graph) == []


@pytest.mark.skipif(not GEMMA.exists(), reason="gemma4-emotion-vectors is not checked out here")
def test_gemma4_emotion_vectors_loads_clean_with_no_drift() -> None:
    graph = load(GEMMA)
    orphan_report(graph)
    assert drift_report(GEMMA, graph) == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
