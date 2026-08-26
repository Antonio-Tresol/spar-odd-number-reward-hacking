"""Explainers: self-contained HTML pages built from the results, versioned beside them.

An explainer is a deliverable, so it is built by the package from the files
under `results/` and `notes/` rather than assembled by hand, and the built
page is committed so it can be opened from any checkout without a build. The
page embeds its data as one JSON block; everything interactive is inline
JavaScript in the template under `templates/`.

The trace explainer carries every trace with its reader note, the per-cell
rates, and the ten per-model syntheses (their structured summaries from
`results/trace-readings/syntheses.json`, their documents rendered from
`notes/trace-syntheses/`).
"""

from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import markdown

from odd_number.readings import Reading, TraceKey, load_readings, trace_key
from odd_number.traces import Trace, chunk_traces, load_traces

TEMPLATE_DIR = Path(__file__).parent / "templates"
TRACE_EXPLAINER_TEMPLATE = TEMPLATE_DIR / "odd-number-traces.html"

#: The marker the template carries where its data goes.
DATA_MARKER = "__DATA__"


@dataclass(frozen=True, slots=True)
class Hypothesis:
    claim: str
    evidence: str
    against: str
    confidence: str


@dataclass(frozen=True, slots=True)
class Exemplar:
    chunk_id: str
    index: int
    why: str


@dataclass(frozen=True, slots=True)
class Synthesis:
    """One model's synthesis: the structured summary plus its rendered document."""

    model: str
    summary: str
    hypotheses: tuple[Hypothesis, ...]
    exemplars: tuple[Exemplar, ...]
    grading_issues: tuple[str, ...]
    markdown_html: str


def synthesis_document(syntheses_dir: Path, model: str) -> Path:
    return syntheses_dir / f"{model.replace('/', '-')}.md"


def load_syntheses(readings_dir: Path, syntheses_dir: Path) -> list[Synthesis]:
    """The structured syntheses, each with its Markdown document rendered to HTML."""
    rows = json.loads((readings_dir / "syntheses.json").read_text(encoding="utf-8"))["syntheses"]
    syntheses: list[Synthesis] = []
    for row in rows:
        document = synthesis_document(syntheses_dir, row["model"]).read_text(encoding="utf-8")
        syntheses.append(
            Synthesis(
                model=row["model"],
                summary=row["summary"],
                hypotheses=tuple(
                    Hypothesis(
                        claim=h["claim"],
                        evidence=h["evidence"],
                        against=h["against"],
                        confidence=h["confidence"],
                    )
                    for h in row["hypotheses"]
                ),
                exemplars=tuple(
                    Exemplar(chunk_id=e["chunk_id"], index=int(e["index"]), why=e["why"])
                    for e in row["exemplars"]
                ),
                grading_issues=tuple(row["grading_issues"]),
                markdown_html=markdown.markdown(document, extensions=["tables", "fenced_code"]),
            ),
        )
    return syntheses


def describe_trace(trace: Trace, reading: Reading | None) -> dict[str, Any]:
    return {
        "file": trace.file,
        "model": trace.model,
        "treatment": trace.treatment,
        "condition": trace.condition,
        "index": trace.index,
        "parity": trace.parity,
        "number": trace.number,
        "source": trace.answer_source,
        "finish": trace.finish_reason,
        "chars": len(trace.reasoning),
        "reasoning": trace.reasoning,
        "response": trace.response,
        "note": None
        if reading is None
        else {
            "reader": reading.reader,
            "chunk": reading.chunk,
            "reads_grader": reading.reads_grader,
            "grader_reading": reading.grader_reading,
            "situation": reading.situation,
            "decision": reading.decision,
            "quotes": list(reading.quotes),
            "labels": list(reading.labels),
            "interesting": reading.interesting,
            "why_interesting": reading.why_interesting,
            "answer_as_read": reading.answer_as_read,
        },
    }


def describe_cells(traces: list[Trace], readings: dict[TraceKey, Reading]) -> list[dict[str, Any]]:
    """Per (file, treatment): counts, the odd count, median reasoning length, the prompt, the reader."""
    groups: dict[tuple[str, str], list[Trace]] = {}
    for trace in traces:
        groups.setdefault((trace.file, trace.treatment), []).append(trace)
    cells: list[dict[str, Any]] = []
    for (file, treatment), members in sorted(groups.items()):
        parseable = [t for t in members if t.parity in ("odd", "even")]
        readers = {readings[trace_key(t)].reader for t in members if trace_key(t) in readings}
        cells.append(
            {
                "file": file,
                "model": members[0].model,
                "treatment": treatment,
                "n": len(members),
                "parseable": len(parseable),
                "odd": sum(1 for t in parseable if t.parity == "odd"),
                "median_chars": statistics.median(len(t.reasoning) for t in members),
                "prompt": members[0].prompt,
                "reader": " + ".join(sorted(readers)) or None,
            },
        )
    return cells


def build_trace_explainer_data(
    results_dir: Path, readings_dir: Path, syntheses_dir: Path
) -> dict[str, Any]:
    traces = load_traces(results_dir)
    readings = load_readings(chunk_traces(traces), readings_dir)
    return {
        "traces": [describe_trace(t, readings.get(trace_key(t))) for t in traces],
        "cells": describe_cells(traces, readings),
        "syntheses": {s.model: asdict(s) for s in load_syntheses(readings_dir, syntheses_dir)},
    }


def embed_json(data: dict[str, Any]) -> str:
    """JSON that is safe inside a `<script type="application/json">` block.

    `<` is escaped as `\\u003c`, which JSON.parse reads back as `<`, so no
    `</script>` or comment opener can occur inside the block.
    """
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def build_trace_explainer(
    results_dir: Path,
    readings_dir: Path,
    syntheses_dir: Path,
    out: Path,
    template: Path = TRACE_EXPLAINER_TEMPLATE,
) -> Path:
    """Write the trace explainer page and return its path."""
    page = template.read_text(encoding="utf-8")
    if page.count(DATA_MARKER) != 1:
        raise ValueError(f"{template} must contain {DATA_MARKER} exactly once")
    data = build_trace_explainer_data(results_dir, readings_dir, syntheses_dir)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page.replace(DATA_MARKER, embed_json(data)), encoding="utf-8")
    return out
