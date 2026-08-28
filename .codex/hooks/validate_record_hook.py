#!/usr/bin/env python3
"""Codex PostToolUse hook: re-validate the record after any tool call.

Claude Code's validator hook reads the edited file path from the event
payload and runs only on edits to the two record files. Codex sends a
different payload per tool, and its file-editing tool does not carry a
plain file path, so this hook does not parse the payload at all. It
hashes TREE.md and RESEARCH_LOG.md, keeps the last hash in the system
temp directory, and runs the validator only when the files actually
changed. The guard costs a few milliseconds per tool call; the validator
runs only when there is something new to check.

The feedback contract is the one both agents document: exit 0 silently
when there is nothing to say, exit 2 with the report on stderr when the
record is broken, so the failure lands back in the agent's context.
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def project_root() -> Path:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        payload = {}
    if isinstance(payload, dict) and payload.get("cwd"):
        return Path(str(payload["cwd"]))
    return Path(os.environ.get("CODEX_PROJECT_DIR", "."))


def record_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for name in ("TREE.md", "RESEARCH_LOG.md"):
        path = root / name
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def main() -> int:
    root = project_root()
    if not (root / "TREE.md").is_file():
        return 0
    validator = root / "scripts" / "validate_research.py"
    if not validator.is_file():
        return 0
    current = record_hash(root)
    marker = Path(tempfile.gettempdir()) / (
        "record-validate-" + hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:16]
    )
    try:
        if marker.is_file() and marker.read_text(encoding="utf-8").strip() == current:
            return 0
    except OSError:
        pass
    try:
        proc = subprocess.run(
            [sys.executable, str(validator)],
            capture_output=True,
            text=True,
            timeout=90,
            cwd=root,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 0
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout + proc.stderr)
        return 2
    try:
        marker.write_text(current, encoding="utf-8")
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
