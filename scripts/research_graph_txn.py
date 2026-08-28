#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Layer 3 (operations): the one write contract every record command shares.

The markdown files are the database, so a write that would leave the record
invalid must never survive on disk. That guarantee lives here, in one place,
rather than being re-implemented per command: take a snapshot of the files
about to change, apply the edit, run the project's validator as a separate
process, then either keep the change or put every file back exactly as it
was — including removing a file that did not exist before.

The refusals that precede a write (a missing record file, an evidence path
that cannot be stored as written) live here too, so that every command
refuses in the same voice and returns the same exit code.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from research_graph_model import INVALID, OK  # noqa: E402

REJECTION_LINE: Final[str] = "Rejected — the record would become invalid; nothing was written:"


def refuse(message: str) -> int:
    """Print a plain-language refusal and return the failure exit code."""
    print(message)
    return INVALID


def reject_joined_paths(evidence: Sequence[str]) -> int | None:
    """Refuse an evidence path with a comma in it, naming the correct form.

    Evidence is stored comma-separated, so a value like "a.json,b.json" becomes
    two paths that each fail the exists-on-disk check with a confusing message.
    Authors reach for it because the record's own format looks like a list; the
    command wants the paths space-separated instead.
    """
    joined = [path for path in evidence if "," in path]
    if not joined:
        return None
    return refuse(
        f"Evidence path {joined[0]!r} contains a comma. Pass each path as its own "
        "argument, separated by spaces, not joined into one string: "
        "--evidence results/first.json results/second.json"
    )


def missing_file(path: Path) -> int:
    return refuse(
        f"There is no {path.name} in this project (looked for {path}). Copy the file from "
        "the research harness templates and fill it in before recording anything."
    )


def write_transaction(
    root: Path,
    files: dict[Path, str],
    preview: list[str],
    confirmation: str,
    dry_run: bool = False,
) -> int:
    """Write the given files together, keeping them only if the validator accepts them.

    Files are written in the order they appear, which matters when one of them is
    evidence for another. On failure every file goes back to its previous content, and
    a file that did not exist before is removed again.

    A dry run is a real rehearsal, not a preview: it writes, validates, and then
    restores whatever the verdict was. Printing the lines without validating them
    told authors a write would succeed and then rejected the identical command a
    moment later, which is worse than no preview at all.
    """
    validator = root / "scripts" / "validate_research.py"
    if not validator.exists():
        return refuse(
            f"There is no validator at {validator}, so this write cannot be checked. Copy "
            "scripts/validate_research.py into the project and run the command again."
        )
    snapshot: dict[Path, bytes | None] = {
        path: (path.read_bytes() if path.exists() else None) for path in files
    }
    for path, text in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(validator)], cwd=root, capture_output=True, text=True, check=False
    )
    if dry_run:
        _restore(snapshot)
        print("Dry run — nothing was written. These are the lines the command would write:")
        for line in preview:
            print(line)
        if result.returncode == 0:
            print("The record would still be valid after this write.")
            return OK
        print("\nBut the write would be REJECTED, because the record would be invalid:")
        print((result.stdout + result.stderr).rstrip())
        return INVALID
    if result.returncode == 0:
        print(confirmation)
        return OK
    _restore(snapshot)
    print(REJECTION_LINE)
    print((result.stdout + result.stderr).rstrip())
    _report_preexisting(root, validator)
    return INVALID


def _report_preexisting(root: Path, validator: Path) -> None:
    """Say so when the record was already invalid before this command ran.

    The rejection above lists whatever the validator found, which may be a
    violation this write neither caused nor could fix — an over-long node
    already in the tree, say. Without this line an author reads the refusal as
    "my command was wrong" and stops using the tool; one measured run abandoned
    the writing commands entirely after exactly that misreading.
    """
    before = subprocess.run(
        [sys.executable, str(validator)], cwd=root, capture_output=True, text=True, check=False
    )
    if before.returncode == 0:
        return
    print(
        "\nNote: the record was ALREADY invalid before this command ran, so this "
        "write is not necessarily what broke it. Nothing was written either way. "
        "Fix the violations above that your change did not introduce — the "
        "set-text command rewrites an over-long node's text in place, keeping its "
        "status and evidence — then run the same command again."
    )


def _restore(snapshot: dict[Path, bytes | None]) -> None:
    """Put every file back exactly as it was before the write."""
    for path, original in snapshot.items():
        if original is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(original)
