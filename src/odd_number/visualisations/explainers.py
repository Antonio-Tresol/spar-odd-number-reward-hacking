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

from odd_number.answers import read_answer_literally
from odd_number.branches import find_source_rollout, split_sentences
from odd_number.readings import Reading, TraceKey, load_readings, trace_key
from odd_number.rollouts import read_rollouts
from odd_number.traces import Trace, chunk_traces, load_traces
from odd_number.visualisations.branch_curves import read_branch_curve

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
        "id": trace.id,
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


def describe_branch_curve(path: Path, results_dir: Path) -> dict[str, Any]:
    """One sweep: its source trace split into sentences, and the rate at each cut.

    The whole point of this view is reading the trace and watching the rate move,
    so the sentences travel with the curve rather than being looked up later.

    `sentences_kept = k` holds indices 0 to k-1, so a rate belongs in the gap
    *after* index k-1. That is computed here, once, because reading it as "the
    rate at sentence k" is the off-by-one that already put one claim in this
    project a sentence late. `after_index` of -1 is the empty prefix: the model
    answering from the prompt with none of its own reasoning.

    Resamples themselves are not carried. There are 1,529 of them across the
    sweeps and nothing in the page reads one, so only the counts travel.
    """
    curve = read_branch_curve(path, path.stem)
    rows = read_rollouts(path)
    first = rows[0]
    source = find_source_rollout(
        results_dir / first["source_file"], first["treatment"], int(first["source_index"])
    )
    return {
        "id": path.stem,
        "source_file": first["source_file"],
        "source_index": int(first["source_index"]),
        "source_parity": first["source_parity"],
        "source_answer": read_answer_literally(source.get("response") or "").number,
        "prompt": source.get("prompt") or "",
        "sentences": split_sentences(source.get("reasoning") or ""),
        "points": [
            {
                "kept": rate.sentences_kept,
                "after_index": rate.sentences_kept - 1,
                "chars": rate.prefix_chars,
                "n": rate.trials,
                "odd": rate.odd,
            }
            for rate in curve.rates
        ],
    }


def describe_branch_curves(branches_dir: Path, results_dir: Path) -> list[dict[str, Any]]:
    """Every sweep on disk, or nothing if none has been run."""
    if not branches_dir.is_dir():
        return []
    return [describe_branch_curve(p, results_dir) for p in sorted(branches_dir.glob("*.jsonl"))]


def describe_interview(path: Path) -> dict[str, Any]:
    """One interview session: the replayed rollout, then every turn in order.

    Both sides are carried, which is the point of the record: the model's answer
    and its chain of thought, and the interviewer's reason for asking and note on
    the reply. Reading only the answers would be reading a self-report as if it
    were evidence, which `notes/interview-protocol.md` exists to prevent.
    """
    rows = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    head = rows[0]
    return {
        "session": head["session"],
        "model": head["model"],
        "source_file": head["source_file"],
        "treatment": head["treatment"],
        "index": int(head["index"]),
        "seed_number": head.get("seed_number"),
        "seed_parity": head.get("seed_parity"),
        "interviewer": head.get("interviewer"),
        "cost_usd": round(sum(float(r.get("cost_usd") or 0) for r in rows), 4),
        "turns": [
            {
                "turn": int(row["turn"]),
                "role": row["role"],
                "kind": row["kind"],
                "content": row.get("content") or "",
                "reasoning": row.get("reasoning") or "",
                "rationale": row.get("rationale") or "",
                "quotes": list(row.get("quotes") or []),
                "tags": list(row.get("tags") or []),
                "observes_turn": row.get("observes_turn"),
            }
            for row in rows
        ],
    }


def describe_interviews(interviews_dir: Path) -> list[dict[str, Any]]:
    """Every interview session on disk, or nothing if none has been run."""
    if not interviews_dir.is_dir():
        return []
    return [describe_interview(p) for p in sorted(interviews_dir.glob("*.jsonl"))]


def build_trace_explainer_data(
    results_dir: Path,
    readings_dir: Path,
    syntheses_dir: Path,
    branches_dir: Path,
    interviews_dir: Path,
) -> dict[str, Any]:
    traces = load_traces(results_dir)
    readings = load_readings(chunk_traces(traces), readings_dir)
    return {
        "traces": [describe_trace(t, readings.get(trace_key(t))) for t in traces],
        "cells": describe_cells(traces, readings),
        "syntheses": {s.model: asdict(s) for s in load_syntheses(readings_dir, syntheses_dir)},
        "branches": describe_branch_curves(branches_dir, results_dir),
        "interviews": describe_interviews(interviews_dir),
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
    branches_dir: Path | None = None,
    interviews_dir: Path | None = None,
) -> Path:
    """Write the trace explainer page and return its path.

    `branches_dir` and `interviews_dir` default to their places under
    `results_dir`, and a missing one yields an empty section rather than an
    error: a checkout that has run neither still builds a page.
    """
    page = template.read_text(encoding="utf-8")
    if page.count(DATA_MARKER) != 1:
        raise ValueError(f"{template} must contain {DATA_MARKER} exactly once")
    data = build_trace_explainer_data(
        results_dir,
        readings_dir,
        syntheses_dir,
        branches_dir if branches_dir is not None else results_dir / "branches",
        interviews_dir if interviews_dir is not None else results_dir / "interviews",
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page.replace(DATA_MARKER, embed_json(data)), encoding="utf-8")
    return out
