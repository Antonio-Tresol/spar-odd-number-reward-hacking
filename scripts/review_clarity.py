#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Ask an independent reader what a research partner cannot follow in a document.

The reader stands in for the person the record is actually for: a research
partner who shares the work but none of the writer's saved state — not the
context window, not the memory files, not the scratch notes. The same
colleague next month, the next agent session, a collaborator seeing the
repository for the first time: all of them read from the record alone.
Independence is not estrangement; it is what lets their reading tell the
truth.

The mechanical checks in this project can tell you that a sentence contains
"w/" or that a node runs past 1,200 characters. They cannot tell you that a
paragraph is unreadable, and the phrase-level survey that tries to approximate
it flags ordinary English often enough that it has to stay advisory. Whether
prose communicates is a judgement, and an agent can make it where a checker
cannot.

The reader has to be independent, and that is the whole reason this is a
separate process rather than a prompt. An agent reviewing prose written in its
own session will pass it, because a name invented in that session is
transparent to the writer by construction. This project's measured failure is
exactly that: agents write for a reader who shares their context window. So
the reader here starts from nothing. It receives the protocol and the text,
inline, and no tools whatsoever — it cannot open the repository, read the
conversation that produced the document, or look up what a term meant
somewhere else. What it cannot follow from the text alone is the finding.

Every complaint must quote the document verbatim, which is what makes the
result checkable rather than a vibe: ``research_graph_review.py`` resolves
each quote against the file and rejects any that is not there. The review is
stamped with a hash of the text that was read, so a later edit makes the
review visibly stale instead of silently wrong.

Usage:

    uv run scripts/review_clarity.py TREE.md
    uv run scripts/review_clarity.py RESEARCH_LOG.md --readers 2
    uv run scripts/review_clarity.py TREE.md --dry-run   # print the prompt only

Nothing this writes can fail a build. A semantic verdict that can block a
commit is a semantic verdict that gets bypassed once and then forever; the
review record is the deliverable, and the pre-commit reminder that points at a
missing or stale one is the only mechanical consequence.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any, Final, NamedTuple

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from research_graph_review import (  # noqa: E402
    REVIEW_DIR,
    content_hash,
    load_review,
    slug_for,
)

EXIT_OK: Final[int] = 0
EXIT_FAIL: Final[int] = 1


class ReaderConfig(NamedTuple):
    """How to run the readers: which model, how many, and how long to wait."""

    model: str = "sonnet"
    readers: int = 1
    timeout: int = 300
    dry_run: bool = False


# Registered before any reading happens, stored verbatim in every review, and
# changed only deliberately: a protocol written after the findings can be
# shaped to them, and a protocol that drifts between runs makes two reviews
# incomparable.
PROTOCOL: Final[str] = (
    "Read this document as a researcher who knows machine learning, statistics, "
    "and software engineering, but has never opened this repository, has not "
    "read its code, and was not present for any conversation about it. Report "
    "every place where the text does not communicate to you, quoting the exact "
    "words verbatim and saying what you cannot tell from them. Report only what "
    "you genuinely cannot follow; writing you understand but would have phrased "
    "differently is not a finding."
)

_LOOK_FOR: Final[str] = """Look for these in particular:
- A name or phrase used as though you should already know it, which no textbook,
  paper, or tool documentation would use with that meaning.
- A sentence you cannot parse without opening the codebase.
- Shorthand or an abbreviation that is not standard in the field.
- A reference to something earlier in the project that is never explained where
  it is used.
- A sentence whose meaning changes depending on how you read it.

Do NOT report:
- Standard field vocabulary: AUC, KL divergence, n, p-value, fp32, LoRA, seeds,
  arms, ablation, and the like. You know these.
- Ordinary English used ordinarily.
- File paths and identifiers in backticks where the sentence around them
  explains what they are.
- Anything you can follow. A complaint about writing that communicates costs
  this project more than it is worth, because a reader who cries wolf gets
  ignored and takes their real findings with them."""

_OUTPUT_CONTRACT: Final[str] = """You have no tools in this session, deliberately:
you are reading as the research partner who has only this document. Do not try
to open files or run commands — reply with one JSON object directly and
nothing else:

{"verdict": "clear" | "needs-work",
 "findings": [{"excerpt": "<the exact words from the document, copied \
character for character>", "problem": "<what you cannot tell, in one sentence>"}]}

Every "excerpt" must be copied verbatim from the document — at least 15
characters, long enough to locate unambiguously. An excerpt that does not
appear in the document is discarded and counts against the review. Use
"clear" with an empty findings list if you followed everything."""


def build_prompt(artifact: str, text: str) -> str:
    """The complete, self-contained reader prompt: protocol, then the document."""
    return (
        f"{PROTOCOL}\n\n{_LOOK_FOR}\n\n{_OUTPUT_CONTRACT}\n\n"
        f"The document is `{artifact}`. It begins after this line and runs to "
        f"the end of the message.\n\n{text}"
    )


def _extract_json(raw: str) -> dict[str, Any] | None:
    """The reader's JSON object, whether or not it wrapped it in a fence."""
    candidates = [raw]
    if "```" in raw:
        parts = raw.split("```")
        candidates.extend(part[4:] if part.startswith("json") else part for part in parts[1::2])
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end > start:
        candidates.append(raw[start : end + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate.strip())
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and "verdict" in parsed:
            return parsed
    return None


def _run_override_reader(
    override: str, prompt: str, neutral: Path, timeout: int
) -> dict[str, Any] | None:
    """Run the RESEARCH_READER_CMD agent command instead of the Claude CLI.

    The override is split into arguments without a shell, and each token's
    ``{prompt_file}`` is replaced with the path of a file holding the reader
    prompt. The command must print the reader's JSON object on stdout.
    """
    prompt_file = neutral / "prompt.txt"
    prompt_file.write_text(prompt, encoding="utf-8")
    argv = [token.replace("{prompt_file}", str(prompt_file)) for token in shlex.split(override)]
    done = subprocess.run(
        argv, capture_output=True, text=True, timeout=timeout, check=False, cwd=neutral
    )
    if done.returncode != 0:
        print(
            f"reader command failed (exit {done.returncode}): {done.stderr[:200]}",
            file=sys.stderr,
        )
        return None
    return _extract_json(done.stdout)


def _one_reader_attempt(prompt: str, model: str, timeout: int) -> dict[str, Any] | None:
    """A single reader process, or None on any failure.

    ``--allowedTools`` is empty on purpose, and the process runs in an empty
    temporary directory rather than wherever the caller stands: the reader has
    the document in its prompt and must have nothing else. An agent process
    started inside the reviewed project would load that project's settings,
    instructions, and skills — exactly the context the intended reader does
    not have, quietly restored by a working directory.

    The turn budget is above one because readers of a record that names its
    evidence files sometimes try to open them — a sound instinct the sandbox
    must absorb rather than punish. The attempt is denied (every tool is),
    the denial comes back as feedback, and the reader answers from the text
    alone; with a single turn, that first attempt killed the read, and six
    reads of one document died this way reporting what looked like API
    errors until the trace was read.
    """
    override = os.environ.get("RESEARCH_READER_CMD", "").strip()
    try:
        with tempfile.TemporaryDirectory(prefix="clarity-reader-") as neutral:
            if override:
                return _run_override_reader(override, prompt, Path(neutral), timeout)
            cmd = [
                "claude",
                "-p",
                prompt,
                "--output-format",
                "json",
                "--model",
                model,
                "--max-turns",
                "4",
                "--allowedTools",
                "",
            ]
            done = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout, check=False, cwd=neutral
            )
    except subprocess.TimeoutExpired as exc:
        print(f"reader failed: {exc}", file=sys.stderr)
        return None
    except FileNotFoundError:
        print(
            "The independent reader is run by an agent command-line tool, and "
            "none was found. By default it uses the Claude Code CLI (claude). "
            "Install that, or set RESEARCH_READER_CMD to a shell command for "
            "another agent: it receives the reader prompt at {prompt_file} "
            "and must print the reader's JSON object on standard output.",
            file=sys.stderr,
        )
        return None
    try:
        envelope = json.loads(done.stdout)
    except json.JSONDecodeError:
        print(f"reader returned no JSON envelope: {done.stdout[:200]}", file=sys.stderr)
        return None
    if envelope.get("is_error"):
        detail = envelope.get("result") or envelope.get("api_error_status")
        print(f"reader errored: {str(detail)[:200]}", file=sys.stderr)
        return None
    return _extract_json(str(envelope.get("result", "")))


def run_reader(prompt: str, model: str, timeout: int) -> dict[str, Any] | None:
    """One reader's answer, retrying once because transient API errors happen.

    A dead reader must read as a dead reader, never as a clean verdict — the
    same rule the eval runners learned when three API-death rows masqueraded
    as refusals. One retry absorbs the transient case; a second failure is
    reported and the run simply contributes nothing.
    """
    for attempt in (1, 2):
        parsed = _one_reader_attempt(prompt, model, timeout)
        if parsed is not None:
            return parsed
        if attempt == 1:
            print("retrying the reader once ...", file=sys.stderr)
    return None


def _shape_run(parsed: dict[str, Any], model: str, today: str) -> dict[str, Any]:
    """One reader's answer as a review run, with anything malformed dropped."""
    findings = [
        {"excerpt": str(f["excerpt"]), "problem": str(f["problem"])}
        for f in parsed.get("findings") or []
        if isinstance(f, dict) and f.get("excerpt") and f.get("problem")
    ]
    verdict = str(parsed.get("verdict", "")).strip()
    if verdict not in {"clear", "needs-work"}:
        verdict = "needs-work" if findings else "clear"
    return {"reader": model, "at": today, "verdict": verdict, "findings": findings}


def run_review(root: Path, artifact: str, config: ReaderConfig) -> int:
    """Read the artifact with independent readers and write the review record.

    This is the engine behind `research_graph.py review --run`; the record
    CLI is the front door, and this module is only its instrument.
    """
    target = root / artifact
    if not target.is_file():
        print(f"no such document: {artifact}", file=sys.stderr)
        return EXIT_FAIL
    text = target.read_text(encoding="utf-8")
    prompt = build_prompt(artifact, text)
    if config.dry_run:
        print(prompt)
        return EXIT_OK
    today = date.today().isoformat()
    runs: list[dict[str, Any]] = []
    for index in range(config.readers):
        print(f"reader {index + 1}/{config.readers} reading {artifact} ...", file=sys.stderr)
        parsed = run_reader(prompt, config.model, config.timeout)
        if parsed is None:
            continue
        runs.append(_shape_run(parsed, config.model, today))
    if not runs:
        print("no reader completed; nothing written", file=sys.stderr)
        return EXIT_FAIL
    record: dict[str, Any] = {
        "artifact": artifact,
        "sha256": content_hash(target),
        "protocol": PROTOCOL,
        "runs": runs,
    }
    out_dir = root / REVIEW_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{slug_for(artifact)}.json"
    # A re-read replaces the runs — the fresh reading is the current review —
    # but never the waivers: each is a recorded decision, and deleting a
    # recorded decision silently is exactly what this project's clean-up rule
    # forbids. A waiver the new readers no longer justify shows up as the
    # dangling-waiver warning, which says to delete it deliberately.
    previous = load_review(out_path)
    if previous is not None and previous.waivers:
        record["waivers"] = previous.waivers
    out_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    total = sum(len(run["findings"]) for run in runs)
    print(f"{out_path.relative_to(root)}: {len(runs)} reader(s), {total} finding(s)")
    return EXIT_OK


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ask an independent reader what a research partner outside "
        "this session cannot follow.",
        epilog="Findings are advisory: this never fails a build.",
    )
    parser.add_argument("artifact", help="Path to the document, relative to --root.")
    parser.add_argument("--root", type=Path, default=Path("."), help="Project root.")
    parser.add_argument("--model", default="sonnet", help="Reader model (default: sonnet).")
    parser.add_argument(
        "--readers", type=int, default=1, help="Independent readers to run (default: 1)."
    )
    parser.add_argument("--timeout", type=int, default=300, help="Seconds per reader.")
    parser.add_argument(
        "--dry-run", action="store_true", help="Print the reader prompt and write nothing."
    )
    args = parser.parse_args()
    config = ReaderConfig(
        model=args.model, readers=args.readers, timeout=args.timeout, dry_run=args.dry_run
    )
    return run_review(args.root.resolve(), args.artifact, config)


if __name__ == "__main__":
    sys.exit(main())
