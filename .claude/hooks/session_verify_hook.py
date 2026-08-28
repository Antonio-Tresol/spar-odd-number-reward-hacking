#!/usr/bin/env python3
"""SessionStart hook: put the record's current health in front of the agent.

The research-log skill asks for `research_graph.py verify` at session start
and after any compaction, because the record is the one source of truth that
survives context loss. That ritual held in measured runs when a skill pointer
was present, but a ritual an agent must remember is a ritual a stripped-down
session forgets. SessionStart is the one hook event whose output the model
actually sees at the right moment (`hookSpecificOutput.additionalContext`),
and it fires on exactly the boundaries the ritual names: a fresh session, a
resume, and the restart after a compaction.

The hook only reports; it decides nothing and blocks nothing. It runs the
same `verify` the agent would run — the whole record pipeline, including
review staleness — and hands over the last lines of its report. In a
repository with no TREE.md there is nothing to verify and the hook says
nothing at all.

Every other hook event was considered for this job and turned down for a
reason worth keeping:

- PreCompact fires at the right moment but its output cannot reach the
  model; the SessionStart firing after compaction covers the same need.
- Stop can force the turn to continue, but everything mechanical it could
  check is already fed back by the PostToolUse validator hook at edit time,
  and anything semantic must never block — a blocked judgement gets
  bypassed once and then forever.
- UserPromptSubmit reaches the model but fires on every message, and this
  project has direct evidence about checkers that talk too often.
"""

import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR", "."))
    if not (root / "TREE.md").is_file():
        return 0
    graph_cli = root / "scripts" / "research_graph.py"
    validator = root / "scripts" / "validate_research.py"
    if graph_cli.is_file():
        cmd = [sys.executable, str(graph_cli), "verify"]
    elif validator.is_file():
        cmd = [sys.executable, str(validator)]
    else:
        return 0
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90, cwd=root)
    except (OSError, subprocess.TimeoutExpired):
        return 0
    tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-12:])
    if not tail:
        return 0
    state = "passing" if proc.returncode == 0 else "FAILING"
    context = (
        f"The research record's integrity check is {state} "
        f"(`research_graph.py verify`, run automatically at session start):\n"
        f"{tail}\n"
        "The record (TREE.md and RESEARCH_LOG.md) is the project's memory "
        "across sessions and compactions; read it before changing beliefs, "
        "and write through the research_graph.py commands."
    )
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": context,
                }
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
