"""Reader notes join back to traces by index, or by position when a reader numbered from zero."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from odd_number.readings import align_notes, load_readings
from odd_number.traces import Trace, chunk_traces


def make_trace(index: int, file: str = "odd-number-m.jsonl") -> Trace:
    return Trace(
        file=file,
        model="m",
        treatment="conflict-grader",
        condition="conflict",
        index=index,
        prompt="P",
        reasoning="r" * 10,
        response="42",
        finish_reason="stop",
        number=42,
        parity="even",
        answer_source="literal",
    )


def test_notes_join_by_index_when_indices_match() -> None:
    chunk = chunk_traces([make_trace(13), make_trace(14)])[0]
    notes = [{"index": 14, "decision": "b"}, {"index": 13, "decision": "a"}]
    aligned = align_notes(chunk, notes)
    assert [(t.index, n["decision"]) for t, n in aligned] == [(14, "b"), (13, "a")]


def test_notes_numbered_from_zero_are_remapped_by_position() -> None:
    chunk = chunk_traces([make_trace(13), make_trace(14)])[0]
    notes = [{"index": 0, "decision": "first"}, {"index": 1, "decision": "second"}]
    aligned = align_notes(chunk, notes)
    assert [(t.index, n["decision"]) for t, n in aligned] == [(13, "first"), (14, "second")]


def test_a_misjoin_is_refused() -> None:
    chunk = chunk_traces([make_trace(13), make_trace(14)])[0]
    with pytest.raises(ValueError):
        align_notes(chunk, [{"index": 99, "decision": "x"}])


def test_load_readings_reads_manifest_notes_and_reports(tmp_path: Path) -> None:
    traces = [make_trace(0), make_trace(1)]
    chunk = chunk_traces(traces)[0]
    readings = tmp_path / "readings"
    readings.mkdir()
    (readings / "manifest.json").write_text(
        json.dumps({"chunks": [{"id": chunk.id, "reader": "claude-sonnet-5"}]})
    )
    (readings / f"{chunk.id}.json").write_text(
        json.dumps(
            [
                {
                    "index": 0,
                    "reads_grader": "yes",
                    "quotes": ["q"],
                    "labels": ["a", "b"],
                    "interesting": True,
                },
                {"index": 1, "reads_grader": "no", "labels": [], "answer_as_read": 42},
            ]
        )
    )
    (readings / f"{chunk.id}.report.md").write_text("# report")
    loaded = load_readings([chunk], readings)
    assert loaded[("odd-number-m.jsonl", "conflict-grader", 0)].labels == ("a", "b")
    assert loaded[("odd-number-m.jsonl", "conflict-grader", 0)].interesting is True
    assert loaded[("odd-number-m.jsonl", "conflict-grader", 1)].answer_as_read == 42
    assert loaded[("odd-number-m.jsonl", "conflict-grader", 1)].reader == "claude-sonnet-5"
