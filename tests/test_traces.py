"""Traces are graded like `grade_records` grades them, and chunked without cutting."""

from __future__ import annotations

import json
from pathlib import Path

from odd_number.answers import JUDGED, UNJUDGED, Answer, response_key
from odd_number.grades import TRUNCATED
from odd_number.traces import (
    Trace,
    build_trace,
    chunk_traces,
    export_trace_chunks,
    read_cached_answer,
    render_chunk,
)


def make_trace(
    index: int, chars: int, treatment: str = "conflict-grader", file: str = "a.jsonl"
) -> Trace:
    return Trace(
        file=file,
        model="m",
        treatment=treatment,
        condition="conflict",
        index=index,
        prompt="P",
        reasoning="r" * chars,
        response="42",
        finish_reason="stop",
        number=42,
        parity="even",
        answer_source="literal",
    )


def test_cached_answer_prefers_literal_then_cache_then_unjudged() -> None:
    cache = {response_key("I pick **7**."): Answer(number=7, source=JUDGED, quote="**7**")}
    assert read_cached_answer("42", cache).number == 42
    assert read_cached_answer("I pick **7**.", cache).number == 7
    assert read_cached_answer("I pick **9**.", cache).source == UNJUDGED


def test_a_truncated_rollout_has_no_answer() -> None:
    record = {
        "treatment": "conflict-grader",
        "index": 3,
        "model": "m",
        "response": "17",
        "finish_reason": "length",
    }
    trace = build_trace(Path("x.jsonl"), record, {})  # type: ignore[arg-type]
    assert trace.number is None
    assert trace.answer_source == TRUNCATED
    assert trace.parity == "unparseable"


def test_chunks_never_mix_treatments_and_respect_the_cap() -> None:
    traces = [make_trace(i, 60) for i in range(5)] + [
        make_trace(i, 60, treatment="agree-grader") for i in range(2)
    ]
    chunks = chunk_traces(traces, max_chars=150)
    assert all(len({t.treatment for t in c.traces}) == 1 for c in chunks)
    assert all(c.chars <= 150 for c in chunks)
    conflict = [c for c in chunks if c.treatment == "conflict-grader"]
    assert [c.part for c in conflict] == [1, 2, 3] and {c.parts for c in conflict} == {3}
    assert [t.index for c in conflict for t in c.traces] == [0, 1, 2, 3, 4]


def test_an_oversized_trace_is_a_chunk_of_its_own_not_cut() -> None:
    chunks = chunk_traces(
        [make_trace(0, 10), make_trace(1, 1000), make_trace(2, 10)], max_chars=100
    )
    assert [[t.index for t in c.traces] for c in chunks] == [[0], [1], [2]]


def test_chunk_ids_are_unique_and_name_their_source() -> None:
    traces = [make_trace(i, 60, file="odd-number-qwen-qwen3.8-27b.jsonl") for i in range(4)]
    ids = [c.id for c in chunk_traces(traces, max_chars=130)]
    assert len(set(ids)) == len(ids)
    assert ids[0] == "qwen-qwen3.8-27b--conflict-grader--1of2"


def test_rendered_chunk_shows_the_prompt_once_and_every_trace() -> None:
    chunk = chunk_traces([make_trace(0, 5), make_trace(1, 5)])[0]
    text = render_chunk(chunk)
    assert text.count("## prompt") == 1
    assert "## trace 0" in text and "## trace 1" in text
    assert "42 (even)" in text


def test_export_writes_chunks_and_a_manifest(tmp_path: Path) -> None:
    results = tmp_path / "results"
    results.mkdir()
    rows = [
        {
            "treatment": "conflict-grader",
            "index": i,
            "model": "m",
            "prompt": "P",
            "response": "3",
            "reasoning": "x",
            "finish_reason": "stop",
            "error": None,
        }
        for i in range(3)
    ]
    (results / "odd-number-m.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    (results / "odd-number-mock.jsonl").write_text(json.dumps(rows[0]) + "\n")
    out = tmp_path / "chunks"
    paths = export_trace_chunks(results, out)
    manifest = json.loads((out / "manifest.json").read_text())
    assert [p.name for p in paths] == ["m--conflict-grader--1of1.md"]
    assert manifest[0]["traces"] == 3 and manifest[0]["odd"] == 3
    assert manifest[0]["keys"][0] == {
        "file": "odd-number-m.jsonl",
        "treatment": "conflict-grader",
        "index": 0,
    }
