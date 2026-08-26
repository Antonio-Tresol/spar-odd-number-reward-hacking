"""Readings: what a reader agent wrote about each trace, joined back to the trace.

The trace-reading workflow (`Q1.H7.E4`) left, per chunk, a JSON list of
per-trace notes and a Markdown report under `results/trace-readings/`, plus a
`manifest.json` naming the reader model for each chunk. A `Reading` is one of
those notes keyed the way traces are keyed, `(file, treatment, index)`.

Three chunk readers numbered their notes from zero instead of by trace index.
The join detects that — the note indices do not match the chunk's trace
indices but the counts do — and remaps by position, which the chunking makes
safe because every chunk lists its traces in index order.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from odd_number.traces import Trace, TraceChunk

TraceKey = tuple[str, str, int]


@dataclass(frozen=True, slots=True)
class Reading:
    """One reader's note on one trace."""

    file: str
    treatment: str
    index: int
    chunk: str
    reader: str
    reads_grader: str
    grader_reading: str
    situation: str
    decision: str
    quotes: tuple[str, ...]
    labels: tuple[str, ...]
    interesting: bool
    why_interesting: str
    answer_as_read: int | None

    @property
    def key(self) -> TraceKey:
        return (self.file, self.treatment, self.index)


@dataclass(frozen=True, slots=True)
class ChunkReading:
    """Everything one reader left about one chunk."""

    chunk: str
    reader: str
    notes: tuple[Reading, ...]
    report: str


def trace_key(trace: Trace) -> TraceKey:
    return (trace.file, trace.treatment, trace.index)


def read_reader_models(readings_dir: Path) -> dict[str, str]:
    """Chunk id → reader model, from the manifest the workflow wrote."""
    manifest = json.loads((readings_dir / "manifest.json").read_text(encoding="utf-8"))
    return {entry["id"]: entry["reader"] for entry in manifest["chunks"]}


def build_reading(chunk: TraceChunk, reader: str, trace: Trace, note: dict[str, object]) -> Reading:
    answer = note.get("answer_as_read")
    return Reading(
        file=trace.file,
        treatment=trace.treatment,
        index=trace.index,
        chunk=chunk.id,
        reader=reader,
        reads_grader=str(note.get("reads_grader") or ""),
        grader_reading=str(note.get("grader_reading") or ""),
        situation=str(note.get("situation") or ""),
        decision=str(note.get("decision") or ""),
        quotes=tuple(str(q) for q in (note.get("quotes") or []) if q),
        labels=tuple(str(label) for label in (note.get("labels") or []) if label),
        interesting=bool(note.get("interesting")),
        why_interesting=str(note.get("why_interesting") or ""),
        answer_as_read=answer if isinstance(answer, int) else None,
    )


def align_notes(
    chunk: TraceChunk, notes: list[dict[str, object]]
) -> list[tuple[Trace, dict[str, object]]]:
    """Pair each note with its trace, by index when the indices match and by position otherwise.

    Raises:
        ValueError: when neither the indices nor the count line up, because a
            misjoined note would silently describe the wrong trace.
    """
    by_index = {trace.index: trace for trace in chunk.traces}
    indices = [note.get("index") for note in notes]
    if sorted(indices) == sorted(by_index):
        return [(by_index[int(str(note["index"]))], note) for note in notes]
    if len(notes) == len(chunk.traces):
        return list(zip(chunk.traces, notes, strict=True))
    raise ValueError(
        f"{chunk.id}: {len(notes)} notes for {len(chunk.traces)} traces and the indices do not match",
    )


def load_chunk_reading(chunk: TraceChunk, readings_dir: Path, reader: str) -> ChunkReading:
    notes = json.loads((readings_dir / f"{chunk.id}.json").read_text(encoding="utf-8"))
    report = (readings_dir / f"{chunk.id}.report.md").read_text(encoding="utf-8")
    aligned = align_notes(chunk, notes)
    return ChunkReading(
        chunk=chunk.id,
        reader=reader,
        notes=tuple(build_reading(chunk, reader, trace, note) for trace, note in aligned),
        report=report,
    )


def load_readings(chunks: list[TraceChunk], readings_dir: Path) -> dict[TraceKey, Reading]:
    """Every reader note, keyed like the traces, for every chunk that has a reading."""
    readers = read_reader_models(readings_dir)
    readings: dict[TraceKey, Reading] = {}
    for chunk in chunks:
        if chunk.id not in readers:
            continue
        for reading in load_chunk_reading(chunk, readings_dir, readers[chunk.id]).notes:
            readings[reading.key] = reading
    return readings
