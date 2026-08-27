"""Traces: every collected rollout with its graded answer, packaged for a reader.

A `Trace` is one rollout as a person or an agent reads it — prompt, chain of
thought, response, and the answer the grading pass assigned — and a
`TraceChunk` is a bundle of traces from one results file and one treatment,
small enough to read in a sitting. `export_trace_chunks` writes the chunks as
Markdown plus a manifest, so the set of traces a reading was done on is a
reproducible artefact rather than whatever happened to be in `results/`.

Answers come from the same two paths as grading — literal, or the judge's
cached verdict — and never from a live call: a trace whose response was
never judged is marked `unjudged`, not guessed.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from odd_number.answers import (
    UNJUDGED,
    Answer,
    judge_cache_path,
    load_cache,
    read_empty_answer,
    read_literal_answer,
    response_key,
)
from odd_number.grades import TRUNCATED, classify_parity, is_complete
from odd_number.rollouts import RolloutRecord, deduplicate_rollouts, read_rollouts

#: Roughly 50k tokens: one chunk fits comfortably in a reader's context with
#: room left for the reading itself.
DEFAULT_MAX_CHARS = 200_000

#: Results files that are not rollouts of the environment (mocks, sidecars).
EXCLUDED_STEMS = ("mock",)

#: Keys every collected rollout carries; see `has_rollouts`.
ROLLOUT_KEYS = ("response", "treatment", "index")


@dataclass(frozen=True, slots=True)
class Trace:
    """One rollout as a reader sees it, with the answer grading assigned it."""

    file: str
    model: str
    treatment: str
    condition: str
    index: int
    prompt: str
    reasoning: str
    response: str
    finish_reason: str
    number: int | None
    parity: str
    answer_source: str

    @property
    def chars(self) -> int:
        return len(self.reasoning) + len(self.response)

    @property
    def id(self) -> str:
        """Stable, human-readable and unique: results-file stem, treatment, index."""
        return f"{file_stem(self.file)}--{self.treatment}--{self.index}"


def file_stem(file: str) -> str:
    return file.removesuffix(".jsonl").removeprefix("odd-number-")


@dataclass(frozen=True, slots=True)
class TraceChunk:
    """Traces from one results file and one treatment, bounded in size."""

    id: str
    file: str
    model: str
    treatment: str
    part: int
    parts: int
    traces: tuple[Trace, ...]

    @property
    def chars(self) -> int:
        return sum(trace.chars for trace in self.traces)


def read_cached_answer(response: str, cache: dict[str, Answer]) -> Answer:
    """The answer grading assigned, without a live judge: literal, empty, cached, or unjudged."""
    literal = read_literal_answer(response) or read_empty_answer(response)
    if literal is not None:
        return literal
    cached = cache.get(response_key(response))
    if cached is not None:
        return cached
    return Answer(number=None, source=UNJUDGED, detail="never judged")


def build_trace(file: Path, record: RolloutRecord, cache: dict[str, Answer]) -> Trace:
    """One trace from one collected record, graded the way `grade_records` grades it."""
    response = record.get("response") or ""
    if is_complete(record):
        answer = read_cached_answer(response, cache)
        number, source = answer.number, answer.source
    else:
        number, source = None, TRUNCATED
    return Trace(
        file=file.name,
        model=record.get("model", ""),
        treatment=record["treatment"],
        condition=record.get("condition", ""),
        index=record["index"],
        prompt=record.get("prompt", ""),
        reasoning=record.get("reasoning") or "",
        response=response,
        finish_reason=record.get("finish_reason", ""),
        number=number,
        parity=classify_parity(number),
        answer_source=source,
    )


def is_rollout_file(path: Path) -> bool:
    """Named like a rollouts file: a `.jsonl` that is not a sidecar or a mock."""
    return (
        path.suffix == ".jsonl"
        and not path.name.endswith(".answers.jsonl")
        and not any(stem in path.name for stem in EXCLUDED_STEMS)
    )


def has_rollouts(path: Path) -> bool:
    """Shaped like rollouts: the first record carries every key a rollout has.

    The name alone is not enough. Another experiment writing its output into
    `results/` would otherwise join the corpus silently and move every count on
    every page built from it.

    `response` is the key that discriminates: the next-turn probe calls its answer
    `replayed_response` and an interview turn calls its text `content`, while both
    carry a `treatment` and an `index` exactly as a rollout does. `condition` is
    deliberately not required, since `build_trace` reads it with a default.
    """
    try:
        for record in read_rollouts(path):
            return all(k in record for k in ROLLOUT_KEYS)
    except (OSError, ValueError):
        return False
    return False


def load_traces(results_dir: Path) -> list[Trace]:
    """Every collected, deduplicated rollout under `results_dir`, graded from cache.

    Files that are not rollouts are skipped rather than parsed into nonsense; use
    `skipped_files` to report which, since a silently narrowed corpus is as wrong
    as a silently widened one.
    """
    traces: list[Trace] = []
    for path in sorted(results_dir.iterdir()):
        if not is_rollout_file(path) or not has_rollouts(path):
            continue
        cache = load_cache(judge_cache_path(path))
        for record in deduplicate_rollouts(read_rollouts(path)):
            traces.append(build_trace(path, record, cache))
    return traces


def skipped_files(results_dir: Path) -> list[Path]:
    """`.jsonl` files in `results_dir` that are named like rollouts but are not."""
    return [
        path
        for path in sorted(results_dir.iterdir())
        if is_rollout_file(path) and not has_rollouts(path)
    ]


def chunk_id(file: str, treatment: str, part: int, parts: int) -> str:
    return f"{file_stem(file)}--{treatment}--{part}of{parts}"


def chunk_traces(traces: list[Trace], max_chars: int = DEFAULT_MAX_CHARS) -> list[TraceChunk]:
    """Group traces by (file, treatment) and split each group so no chunk exceeds `max_chars`.

    A single trace larger than `max_chars` becomes a chunk of its own rather
    than being cut: a severed trace is not a trace.
    """
    groups: dict[tuple[str, str], list[Trace]] = {}
    for trace in traces:
        groups.setdefault((trace.file, trace.treatment), []).append(trace)

    chunks: list[TraceChunk] = []
    for (file, treatment), members in groups.items():
        members = sorted(members, key=lambda trace: trace.index)
        parts: list[list[Trace]] = [[]]
        for trace in members:
            if parts[-1] and sum(t.chars for t in parts[-1]) + trace.chars > max_chars:
                parts.append([])
            parts[-1].append(trace)
        for number, part in enumerate(parts, start=1):
            chunks.append(
                TraceChunk(
                    id=chunk_id(file, treatment, number, len(parts)),
                    file=file,
                    model=part[0].model,
                    treatment=treatment,
                    part=number,
                    parts=len(parts),
                    traces=tuple(part),
                ),
            )
    return chunks


def render_trace(trace: Trace) -> str:
    answer = "no answer" if trace.number is None else f"{trace.number} ({trace.parity})"
    return "\n".join(
        [
            f"## trace {trace.index}  —  {trace.model}  |  {trace.treatment}",
            "",
            f"- answer: {answer}  |  read by: {trace.answer_source}  |  "
            f"finish_reason: {trace.finish_reason or 'unknown'}  |  "
            f"reasoning: {len(trace.reasoning)} chars",
            "",
            "### reasoning",
            "",
            trace.reasoning or "(no chain of thought was returned)",
            "",
            "### response",
            "",
            trace.response or "(empty)",
            "",
        ],
    )


def render_chunk(chunk: TraceChunk) -> str:
    """Markdown a reader can take in top to bottom: the prompt once, then every trace."""
    prompts = {trace.prompt for trace in chunk.traces}
    if len(prompts) != 1:
        raise ValueError(f"{chunk.id}: traces of one treatment must share one prompt")
    odd = sum(1 for trace in chunk.traces if trace.parity == "odd")
    header = [
        f"# {chunk.id}",
        "",
        f"- model: {chunk.model}",
        f"- results file: {chunk.file}",
        f"- treatment: {chunk.treatment}  (part {chunk.part} of {chunk.parts})",
        f"- traces: {len(chunk.traces)}, of which {odd} answered with an odd number",
        "",
        "## prompt (identical for every trace below)",
        "",
        "```",
        prompts.pop(),
        "```",
        "",
    ]
    return "\n".join(header) + "\n" + "\n".join(render_trace(trace) for trace in chunk.traces)


def export_trace_chunks(
    results_dir: Path,
    out_dir: Path,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> list[Path]:
    """Write every chunk as Markdown plus `manifest.json`, and return the chunk paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    chunks = chunk_traces(load_traces(results_dir), max_chars)
    paths: list[Path] = []
    manifest: list[dict[str, object]] = []
    for chunk in chunks:
        path = out_dir / f"{chunk.id}.md"
        path.write_text(render_chunk(chunk), encoding="utf-8")
        paths.append(path)
        manifest.append(
            {
                "id": chunk.id,
                "path": str(path),
                "file": chunk.file,
                "model": chunk.model,
                "treatment": chunk.treatment,
                "part": chunk.part,
                "parts": chunk.parts,
                "traces": len(chunk.traces),
                "odd": sum(1 for trace in chunk.traces if trace.parity == "odd"),
                "chars": chunk.chars,
                "keys": [
                    {k: v for k, v in asdict(trace).items() if k in ("file", "treatment", "index")}
                    for trace in chunk.traces
                ],
            },
        )
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return paths
