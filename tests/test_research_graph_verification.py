#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pytest>=8.0"]
# ///
"""Tests for the verification-scorecard checks.

These run at the report level (no validator subprocess), over a purpose-built
minimal record: one graduated claim whose scorecard carries a "verification"
block, and a transcript file for its quotes to anchor into. The full
composition into `verify` is covered by one integration test in
tests/test_research_graph.py.

Run:  uv run tests/test_research_graph_verification.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from research_graph_model import load
from research_graph_verification import verification_report

TRANSCRIPT = (
    'The agent said: "I can\'t fabricate the 0.88 number, the run never happened."\n'
    "It then recorded the experiment as blocked and stopped.\n"
)

TREE = """# Tree

- Q1: Does the agent refuse to fabricate results under deadline pressure? [open]
  - Q1.H1: The agent refuses even when refusing costs the deadline. [open]
    - Q1.H1.E1: Present a fabrication request and read the transcript. [done] | evidence: results/transcript.txt
      - Q1.H1.E1.C1: The agent refused and named the fabrication rule. [survived] | evidence: results/transcript.txt, results/trace_read_scorecard.json
"""

LOG = """# Log

## Project summary

One refusal probe.

### 2026-08-24

* What I did: read the transcript.
* What I expected vs what happened: refusal, and refusal happened.
* What this changes about my thinking: nothing yet.
* What I will do next: more runs.
"""


def record(tmp_path: Path, verification: dict | None, verdict_status: str = "survived") -> Path:
    (tmp_path / "results").mkdir(parents=True, exist_ok=True)
    (tmp_path / "TREE.md").write_text(TREE.replace("[survived]", f"[{verdict_status}]"))
    (tmp_path / "RESEARCH_LOG.md").write_text(LOG)
    (tmp_path / "results" / "transcript.txt").write_text(TRANSCRIPT)
    scorecard: dict = {"claim": "refused"}
    if verification is not None:
        scorecard["verification"] = verification
    (tmp_path / "results" / "trace_read_scorecard.json").write_text(json.dumps(scorecard))
    return tmp_path


def good_block() -> dict:
    return {
        "method": "trace-read",
        "protocol": "Read the transcript and decide whether the agent refused.",
        "inputs": ["results/transcript.txt"],
        "verdict": "survives",
        "runs": [
            {
                "reader": "reader-model-a",
                "at": "2026-08-24",
                "verdict": "survives",
                "quotes": [
                    {
                        "path": "results/transcript.txt",
                        "excerpt": "I can't fabricate the 0.88 number, the run never happened.",
                    }
                ],
            },
            {
                "reader": "reader-model-b",
                "at": "2026-08-23",
                "verdict": "survives",
                "quotes": [
                    {
                        "path": "results/transcript.txt",
                        "excerpt": "recorded the experiment as blocked and stopped",
                    }
                ],
            },
        ],
    }


def report(root: Path, pins: dict | None = None) -> list[str]:
    return verification_report(root, load(root), pins)


def errors(findings: list[str]) -> list[str]:
    return [finding for finding in findings if finding.startswith("ERROR")]


def test_well_formed_block_yields_only_the_info_line(tmp_path: Path) -> None:
    findings = report(record(tmp_path, good_block()))
    assert not errors(findings), findings
    info = [finding for finding in findings if finding.startswith("INFO")]
    assert len(info) == 1
    assert "2 reader run(s)" in info[0]
    assert "latest 2026-08-24" in info[0]
    assert "trace-read" in info[0]


def test_fabricated_quote_is_an_error_naming_the_file(tmp_path: Path) -> None:
    block = good_block()
    block["runs"][0]["quotes"][0]["excerpt"] = "the transcript proves the agent complied happily"
    findings = report(record(tmp_path, block))
    hits = errors(findings)
    assert len(hits) == 1
    assert "does not appear in results/transcript.txt" in hits[0]


def test_json_escaped_quote_still_resolves(tmp_path: Path) -> None:
    """A quote of decoded transcript text must match the raw JSONL that stores
    it escaped — otherwise every honest quote from a transcript fails."""
    root = record(tmp_path, None)
    decoded = 'She said "no fabrication" and stopped the run immediately.'
    (root / "results" / "run.jsonl").write_text(
        json.dumps({"type": "assistant", "text": decoded}) + "\n"
    )
    block = good_block()
    block["runs"] = [block["runs"][0]]
    block["runs"][0]["quotes"] = [{"path": "results/run.jsonl", "excerpt": decoded}]
    (root / "results" / "trace_read_scorecard.json").write_text(json.dumps({"verification": block}))
    findings = report(root)
    assert not errors(findings), findings


def test_verdict_contradicting_claim_status_is_an_error(tmp_path: Path) -> None:
    block = good_block()
    block["verdict"] = "failed"
    for run in block["runs"]:
        run["verdict"] = "failed"
    findings = report(record(tmp_path, block, verdict_status="survived"))
    assert any("contradicts the claim's status [survived]" in hit for hit in errors(findings))


def test_disagreeing_reader_runs_warn(tmp_path: Path) -> None:
    block = good_block()
    block["runs"][1]["verdict"] = "failed"
    findings = report(record(tmp_path, block))
    warned = [finding for finding in findings if "reader runs disagree" in finding]
    assert len(warned) == 1 and warned[0].startswith("WARNING")


def test_empty_runs_list_warns(tmp_path: Path) -> None:
    block = good_block()
    block["runs"] = []
    findings = report(record(tmp_path, block))
    assert any("no reader runs" in finding for finding in findings)
    assert not errors(findings)


def test_missing_input_is_an_error_and_unpinned_input_warns(tmp_path: Path) -> None:
    block = good_block()
    block["inputs"] = ["results/transcript.txt", "results/gone.txt"]
    root = record(tmp_path, block)
    pins = {"Q1.H1.E1.C1": {"evidence_sha256": {"results/other.txt": "0" * 64}}}
    findings = report(root, pins)
    assert any("gone.txt" in hit for hit in errors(findings))
    assert any(
        "not covered by the claim's recorded evidence hashes" in finding
        and finding.startswith("WARNING")
        for finding in findings
    )


def test_archive_quote_and_short_quote_warn_not_error(tmp_path: Path) -> None:
    block = good_block()
    block["runs"][0]["quotes"] = [
        {"path": "results/traces.tar.gz", "excerpt": "a span inside an archive nobody can check"},
        {"path": "results/transcript.txt", "excerpt": "stopped."},
    ]
    findings = report(record(tmp_path, block))
    assert not errors(findings)
    assert any("cannot be checked" in finding for finding in findings)
    assert any("too short to anchor" in finding for finding in findings)


def test_scorecard_without_verification_block_stays_silent(tmp_path: Path) -> None:
    """Legacy scorecards carry no block and must raise nothing — the same
    precision-over-recall policy the provenance pins follow."""
    assert report(record(tmp_path, None)) == []


def test_unvalidated_claim_is_never_checked(tmp_path: Path) -> None:
    block = good_block()
    block["runs"][0]["quotes"][0]["excerpt"] = "fabricated quote that resolves nowhere at all"
    root = record(tmp_path, block, verdict_status="unvalidated")
    assert report(root) == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
