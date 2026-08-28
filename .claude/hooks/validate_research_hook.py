#!/usr/bin/env python3
"""PostToolUse hook: revalidate after any edit to TREE.md or RESEARCH_LOG.md.

Wired in .claude/settings.json (from templates/claude-settings.json). Exit 2
is the Claude Code contract for "show stderr to the model", so validator
failures land straight back in the agent's context instead of waiting for the
session-end ritual. Behaviour evidence for shipping this lives with
scripts/run_plain_language_eval.py: agents reliably fix what the validator
reports once they see it; the hook removes the need to remember to run it.
Other agents (Codex reads no Claude hooks) still rely on the session-end run.
"""

import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    payload = json.load(sys.stdin)
    edited = str(payload.get("tool_input", {}).get("file_path", ""))
    if not edited:
        return 0
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR", "."))
    # Exact root-file match: editing templates/TREE.md, a fixture, or another
    # project's copy must not trigger a whole-project validation here.
    targets = {(root / name).resolve() for name in ("TREE.md", "RESEARCH_LOG.md")}
    if Path(edited).resolve() not in targets:
        return 0
    validator = root / "scripts" / "validate_research.py"
    if not validator.is_file():
        return 0
    proc = subprocess.run(
        [sys.executable, str(validator)], capture_output=True, text=True, timeout=60
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout + proc.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
