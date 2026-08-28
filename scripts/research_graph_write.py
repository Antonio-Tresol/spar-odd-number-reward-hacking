#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Operations layer: the write commands that record new content in the research record.

Every write follows one contract, implemented once in `research_graph_txn` and reused
by all of them: take a snapshot of the files about to change, apply the edit, run the
project's validator as a separate process, and then either keep the change or put the
files back exactly as they were. The markdown files are the database, so a write that
would leave the record invalid never survives on disk. Each command also accepts
`dry_run`, which rehearses the write and then restores the files untouched.
"""

from __future__ import annotations

import datetime
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

# The validator is the single authority on the grammar of the record, so its parser,
# status vocabulary, and patterns are imported rather than repeated here. It sits in
# the same directory as this file, which is why that directory goes on the path.
_HERE: Final[str] = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import validate_research as grammar  # noqa: E402

# The exit codes are the shared conventions defined once in the model module: success
# is 0 and a refused or rolled-back write is 1. Code 2 is reserved for command-line
# mistakes, which argparse reports in the command-line interface before any function
# here is called.
from research_graph_model import OK  # noqa: E402
from research_graph_txn import missing_file as _missing_file  # noqa: E402
from research_graph_txn import refuse as _refuse  # noqa: E402
from research_graph_txn import reject_joined_paths as _reject_joined_paths  # noqa: E402
from research_graph_txn import (  # noqa: E402
    write_transaction,
)

TYPE_LETTERS: Final[dict[str, str]] = {
    "question": "Q",
    "hypothesis": "H",
    "experiment": "E",
    "claim": "C",
}
# What a node of each type is allowed to start life as.
NEW_NODE_STATUS: Final[dict[str, str]] = {
    "Q": "open",
    "H": "open",
    "E": "planned",
    "C": "unvalidated",
}

FENCES: Final[tuple[str, ...]] = ("```", "~~~")


def _no_such_node(node_id: str) -> int:
    return _refuse(
        f"The research tree has no node called {node_id}. Run the tree command to see the "
        "ids that exist, then use one of those."
    )


def _joined(lines: Sequence[str]) -> str:
    """Turn a list of lines back into file text, always ending with one newline."""
    return "\n".join(lines) + "\n"


def _sentence(text: str) -> str:
    """Trim a piece of prose and end it with a full stop so bullets read as sentences."""
    trimmed = text.strip()
    if trimmed and trimmed[-1] not in ".!?":
        trimmed += "."
    return trimmed


# --------------------------------------------------------------------------------------
# Reading and writing single lines of the research tree.
# --------------------------------------------------------------------------------------


def _read_tree(root: Path) -> tuple[list[str], list[grammar.Node]]:
    """Return the lines of TREE.md and the nodes parsed from them.

    Lines inside fenced examples and lines the validator's parser rejects are skipped:
    reporting on them is the validator's job, not this module's.
    """
    lines = (root / "TREE.md").read_text(encoding="utf-8").splitlines()
    report = grammar.Report()
    nodes: list[grammar.Node] = []
    in_fence = False
    for lineno, line in enumerate(lines, 1):
        if line.lstrip().startswith(FENCES):
            in_fence = not in_fence
            continue
        if in_fence or not grammar.is_node_line(line.strip()):
            continue
        node = grammar.parse_node(line, lineno, report)
        if node is not None:
            nodes.append(node)
    return lines, nodes


def _find_node(nodes: Sequence[grammar.Node], node_id: str) -> grammar.Node | None:
    return next((node for node in nodes if node.node_id == node_id), None)


def _indent_of(line: str) -> str:
    """The blank space a line starts with, kept exactly as it was written.

    The whole prefix is carried across rather than counted, so a line indented with
    tabs comes back with its tabs when only its status or evidence changed.
    """
    return line[: len(line) - len(line.lstrip())]


def _format_node_line(
    indent: str,
    node_id: str,
    text: str,
    status: str,
    evidence: Sequence[str],
    log_date: str | None,
) -> str:
    """Build one node line in the exact shape the validator's grammar expects."""
    line = f"{indent}- {node_id}: {text} [{status}]"
    if evidence:
        line += " | evidence: " + ", ".join(evidence)
    if log_date:
        line += f" | log: {log_date}"
    return line


def _rewrite_node_line(
    lines: list[str],
    node: grammar.Node,
    status: str,
    evidence: Sequence[str],
    log_date: str | None,
) -> str:
    """Replace one node's line in place, keeping its indentation and text, and return it."""
    index = node.lineno - 1
    line = _format_node_line(
        _indent_of(lines[index]), node.node_id, node.text, status, evidence, log_date
    )
    lines[index] = line
    return line


def _merge_paths(existing: Sequence[str], added: Sequence[str]) -> list[str]:
    """Keep the paths already recorded, in order, and append the ones that are new."""
    merged = list(existing)
    for path in added:
        cleaned = path.strip()
        if cleaned and cleaned not in merged:
            merged.append(cleaned)
    return merged


def _next_child_id(nodes: Sequence[grammar.Node], parent_id: str | None, letter: str) -> str:
    """Give the next free id under a parent, counting each type separately.

    The count goes past the highest number in use rather than filling gaps, because a
    number that was retired on purpose must never come back on a different node.
    """
    highest = 0
    for node in nodes:
        if node.parent_id != parent_id:
            continue
        segment = node.node_id.rsplit(".", 1)[-1]
        if segment.startswith(letter) and segment[1:].isdigit():
            highest = max(highest, int(segment[1:]))
    prefix = f"{parent_id}." if parent_id else ""
    return f"{prefix}{letter}{highest + 1}"


def _insertion_line(
    lines: Sequence[str], nodes: Sequence[grammar.Node], parent: grammar.Node | None
) -> int:
    """Line number after which a new child of this parent belongs.

    A new node goes directly below the parent's last descendant, so a family stays
    together. A new question goes below the whole tree.
    """
    if parent is None:
        if not nodes:
            end = len(lines)
            while end > 0 and not lines[end - 1].strip():
                end -= 1
            return end
        return max(node.lineno for node in nodes)
    prefix = f"{parent.node_id}."
    return max([parent.lineno] + [node.lineno for node in nodes if node.node_id.startswith(prefix)])


# --------------------------------------------------------------------------------------
# Write commands over the research tree.
# --------------------------------------------------------------------------------------


def _status_for_new_node(letter: str, requested: str | None) -> tuple[str | None, str]:
    """Decide what status a new node starts with, or explain why the request is refused."""
    if requested is None:
        return NEW_NODE_STATUS[letter], ""
    if letter == "C" and requested != "unvalidated":
        return None, (
            f"A new claim may only be recorded as 'unvalidated', not '{requested}'. A claim "
            "graduates after the falsification gate has run: record it now, write the "
            "scorecard, then change the status with the set-status command."
        )
    if requested not in grammar.STATUS_VOCAB[letter]:
        allowed = ", ".join(sorted(grammar.STATUS_VOCAB[letter]))
        return None, f"'{requested}' is not a status for this kind of node. Use one of: {allowed}."
    return requested, ""


def add_node(
    root: Path,
    parent_id: str | None,
    node_type: str,
    text: str,
    status: str | None,
    evidence: list[str],
    dry_run: bool = False,
) -> int:
    """Add one question, hypothesis, experiment, or claim to TREE.md under its parent."""
    joined = _reject_joined_paths(evidence)
    if joined is not None:
        return joined
    letter = TYPE_LETTERS.get(node_type)
    if letter is None:
        return _refuse(
            f"'{node_type}' is not a kind of node. Use one of: {', '.join(sorted(TYPE_LETTERS))}."
        )
    tree_path = root / "TREE.md"
    if not tree_path.exists():
        return _missing_file(tree_path)
    lines, nodes = _read_tree(root)
    parent: grammar.Node | None = None
    if parent_id:
        parent = _find_node(nodes, parent_id)
        if parent is None:
            return _no_such_node(parent_id)
    elif letter != "Q":
        return _refuse(
            "Only a question can stand on its own at the top of the tree. Give the id of "
            "the node this one belongs under."
        )
    new_status, problem = _status_for_new_node(letter, status)
    if new_status is None:
        return _refuse(problem)
    node_id = _next_child_id(nodes, parent_id, letter)
    indent = _indent_of(lines[parent.lineno - 1]) + "  " if parent else ""
    line = _format_node_line(indent, node_id, text, new_status, evidence, None)
    lines.insert(_insertion_line(lines, nodes, parent), line)
    return write_transaction(
        root,
        {tree_path: _joined(lines)},
        ["TREE.md:", line],
        f"Added {node_id} [{new_status}] to TREE.md.",
        dry_run,
    )


def add_evidence(root: Path, node_id: str, paths: list[str], dry_run: bool = False) -> int:
    """Link one or more evidence files to a node that is already in the tree."""
    joined = _reject_joined_paths(paths)
    if joined is not None:
        return joined
    tree_path = root / "TREE.md"
    if not tree_path.exists():
        return _missing_file(tree_path)
    lines, nodes = _read_tree(root)
    node = _find_node(nodes, node_id)
    if node is None:
        return _no_such_node(node_id)
    merged = _merge_paths(node.evidence, paths)
    if merged == list(node.evidence):
        print(f"{node_id} already lists every one of those paths, so nothing was written.")
        return OK
    line = _rewrite_node_line(lines, node, node.status, merged, node.log_date)
    added = len(merged) - len(node.evidence)
    noun = "path" if added == 1 else "paths"
    return write_transaction(
        root,
        {tree_path: _joined(lines)},
        ["TREE.md:", line],
        f"Linked {added} evidence {noun} to {node_id}.",
        dry_run,
    )


def _graduation_problem(node: grammar.Node, status: str, evidence: Sequence[str]) -> str:
    """Explain why a claim may not graduate yet, or return an empty string when it may."""
    if node.node_type != "C" or status not in grammar.GRADUATED_CLAIM_STATUSES:
        return ""
    if any(grammar.SCORECARD_RE.search(Path(path).name) for path in evidence):
        return ""
    return (
        f"{node.node_id} cannot become '{status}' yet, because none of its evidence is a "
        "scorecard from the falsification gate (a file whose name contains 'falsify', "
        "'scorecard', or 'validation'). Run the falsify skill's tests, save the scorecard, "
        "and set the status again with that file in the evidence list."
    )


def set_status(
    root: Path,
    node_id: str,
    status: str,
    evidence: list[str],
    log_date: str | None,
    dry_run: bool = False,
) -> int:
    """Change a node's status, optionally adding evidence and a log date in the same write."""
    joined = _reject_joined_paths(evidence)
    if joined is not None:
        return joined
    tree_path = root / "TREE.md"
    if not tree_path.exists():
        return _missing_file(tree_path)
    lines, nodes = _read_tree(root)
    node = _find_node(nodes, node_id)
    if node is None:
        return _no_such_node(node_id)
    if status not in grammar.STATUS_VOCAB[node.node_type]:
        allowed = ", ".join(sorted(grammar.STATUS_VOCAB[node.node_type]))
        return _refuse(f"'{status}' is not a status for {node_id}. Use one of: {allowed}.")
    merged = _merge_paths(node.evidence, evidence)
    problem = _graduation_problem(node, status, merged)
    if problem:
        return _refuse(problem)
    line = _rewrite_node_line(lines, node, status, merged, log_date or node.log_date)
    return write_transaction(
        root,
        {tree_path: _joined(lines)},
        ["TREE.md:", line],
        f"{node_id} is now [{status}].",
        dry_run,
    )


def set_text(root: Path, node_id: str, text: str, dry_run: bool = False) -> int:
    """Replace one node's headline text, keeping its status, evidence, and log date.

    The command the record was missing. Every other field had a way to change
    it, but the text itself did not, so the one operation the altitude rule
    actually demands — trimming an over-long node down to a headline after its
    detail moves into a notes/ document — was the operation authors had to do
    by hand. Two measured sessions independently read the source to confirm no
    such command existed before falling back to a hand edit, and a third
    hand-edit slip introduced a log reference to an entry that did not exist
    yet. Rewriting the line here keeps the rest of the node intact by
    construction.
    """
    tree_path = root / "TREE.md"
    if not tree_path.exists():
        return _missing_file(tree_path)
    lines, nodes = _read_tree(root)
    node = _find_node(nodes, node_id)
    if node is None:
        return _no_such_node(node_id)
    cleaned = " ".join(text.split())
    if not cleaned:
        return _refuse(
            f"The new text for {node_id} is empty. A node is a headline: give one or two "
            "plain sentences saying what the thing is and where it stands."
        )
    index = node.lineno - 1
    line = _format_node_line(
        _indent_of(lines[index]),
        node.node_id,
        cleaned,
        node.status,
        node.evidence,
        node.log_date,
    )
    lines[index] = line
    return write_transaction(
        root,
        {tree_path: _joined(lines)},
        ["TREE.md:", line],
        f"Rewrote the text of {node_id}, keeping its status, evidence, and log date.",
        dry_run,
    )


# --------------------------------------------------------------------------------------
# Write commands over the research log.
# --------------------------------------------------------------------------------------


def _entry_headers(lines: Sequence[str]) -> list[tuple[int, str]]:
    """Position and date of every dated entry header, in the order the file holds them."""
    headers: list[tuple[int, str]] = []
    in_fence = False
    for index, line in enumerate(lines):
        if line.lstrip().startswith(FENCES):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = grammar.LOG_HEADER_RE.match(line)
        if match:
            headers.append((index, match.group(1)))
    return headers


def _is_bullet(line: str, label: str) -> bool:
    """True when this line is the entry bullet with the given label, bold or plain."""
    plain = line.replace("*", "").replace("_", "").strip()
    return plain.startswith(label) and plain[len(label) :].lstrip().startswith(":")


def _new_entry_lines(entry_date: str, sentences: Sequence[str]) -> list[str]:
    """Build a whole new entry: the dated header and the four bullets, in order."""
    block = [f"### {entry_date}", ""]
    block += [
        f"* {bullet} {_sentence(sentence)}"
        for bullet, sentence in zip(grammar.LOG_BULLETS, sentences)
    ]
    block.append("")
    return block


def _entry_bounds(
    headers: Sequence[tuple[int, str]], entry_date: str, total: int
) -> tuple[int, int]:
    """The first and last line of the entry carrying this date, as positions in the file."""
    start = next(index for index, entry in headers if entry == entry_date)
    later = [index for index, _ in headers if index > start]
    return start, later[0] if later else total


def _merge_into_entry(
    lines: list[str], start: int, end: int, sentences: Sequence[str]
) -> list[str]:
    """Add each sentence to the end of its bullet in an entry that already exists.

    A bullet the entry is missing is added at the end of it. The changed lines are
    returned so the caller can show them.
    """
    changed: list[str] = []
    tail = end
    while tail > start and not lines[tail - 1].strip():
        tail -= 1
    for bullet, sentence in zip(grammar.LOG_BULLETS, sentences):
        label = bullet.rstrip(":")
        index = next((i for i in range(start + 1, tail) if _is_bullet(lines[i], label)), None)
        if index is None:
            lines.insert(tail, f"* {bullet} {_sentence(sentence)}")
            tail += 1
            changed.append(lines[tail - 1])
        else:
            lines[index] = f"{lines[index].rstrip()} {_sentence(sentence)}"
            changed.append(lines[index])
    return changed


def append_log_entry(
    root: Path,
    date: str | None,
    did: str,
    expected: str,
    changes: str,
    next_step: str,
    dry_run: bool = False,
) -> int:
    """Record today's work in RESEARCH_LOG.md, merging into the day's entry if it exists."""
    log_path = root / "RESEARCH_LOG.md"
    if not log_path.exists():
        return _missing_file(log_path)
    sentences = [did, expected, changes, next_step]
    if not all(sentence.strip() for sentence in sentences):
        return _refuse(
            "An entry answers all four questions, so none of them may be left empty: what "
            "you did, what you expected against what happened, what it changes about your "
            "thinking, and what you will do next."
        )
    entry_date = date or datetime.date.today().isoformat()
    lines = log_path.read_text(encoding="utf-8").splitlines()
    headers = _entry_headers(lines)
    dates = [entry for _, entry in headers]
    if entry_date in dates:
        start, end = _entry_bounds(headers, entry_date, len(lines))
        preview = _merge_into_entry(lines, start, end, sentences)
        confirmation = f"Merged the new sentences into the {entry_date} entry of RESEARCH_LOG.md."
    elif dates and entry_date < dates[0]:
        return _refuse(
            f"The newest entry in the log is {dates[0]}, so an entry for {entry_date} would "
            "put the log out of order. Entries run newest first: add today's entry, or "
            "correct the date."
        )
    else:
        preview = _new_entry_lines(entry_date, sentences)
        at = headers[0][0] if headers else len(lines)
        lines[at:at] = preview
        confirmation = f"Added the {entry_date} entry to RESEARCH_LOG.md."
    return write_transaction(
        root, {log_path: _joined(lines)}, ["RESEARCH_LOG.md:", *preview], confirmation, dry_run
    )


# --------------------------------------------------------------------------------------
# Write command for a notes document.
# --------------------------------------------------------------------------------------


def _note_text(title: str, body: str) -> str:
    """The document a note starts as: a heading, the date it was written, then the body."""
    today = datetime.date.today().isoformat()
    return f"# {title}\n\nDated {today}.\n\n{body.strip()}\n"


def add_note(
    root: Path, slug: str, title: str, body: str, link: str | None, dry_run: bool = False
) -> int:
    """Write a notes document and, when a node id is given, link it there as evidence."""
    if not slug or Path(slug).is_absolute() or ".." in Path(slug).parts:
        return _refuse(
            "The note name must be a simple file name such as 'protocol-2026-08-24', with "
            "no leading slash and no steps up the directory tree."
        )
    note_relative = f"notes/{slug}.md"
    note_path = root / note_relative
    if note_path.exists():
        return _refuse(
            f"{note_relative} already exists. Choose another name, or edit that file directly."
        )
    text = _note_text(title, body)
    files: dict[Path, str] = {note_path: text}
    preview = [f"{note_relative}:", *text.splitlines()]
    confirmation = f"Wrote {note_relative}."
    if link:
        tree_path = root / "TREE.md"
        if not tree_path.exists():
            return _missing_file(tree_path)
        lines, nodes = _read_tree(root)
        node = _find_node(nodes, link)
        if node is None:
            return _no_such_node(link)
        merged = _merge_paths(node.evidence, [note_relative])
        line = _rewrite_node_line(lines, node, node.status, merged, node.log_date)
        files[tree_path] = _joined(lines)
        preview += ["TREE.md:", line]
        confirmation = f"Wrote {note_relative} and linked it as evidence on {link}."
    return write_transaction(root, files, preview, confirmation, dry_run)
