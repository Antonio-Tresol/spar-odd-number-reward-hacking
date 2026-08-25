#!/usr/bin/env bash
# Every mechanical check, in one command.
#
#   lanorme  — code quality, Agent Skills spec compliance, and the harness's own
#              plugins (tensors, skill_portability, provenance). PYTHONPATH=. is
#              what lets lanorme import them from lanorme_plugins/.
#   pytest   — the checks' own tests, including a false-positive suite. A checker
#              that cries wolf gets bypassed, so quiet-on-clean-input is tested
#              as carefully as fires-on-bad-input.
#   validate_research.py — the research-integrity gate. Deliberately standalone
#              and dependency-free: a project that never installs lanorme must
#              still have every integrity guarantee. Skipped in the harness repo
#              itself, which is not a research project and has no TREE.md.
set -euo pipefail
cd "$(dirname "$0")"

# Formatting and import order are not up for debate: ruff format + isort (rule I).
uvx ruff format --check . && uvx ruff check --select I .

PYTHONPATH=. uvx lanorme check "${1:-.}"

if [[ -d tests ]]; then
    uv run --with pytest --with lanorme pytest tests -q
fi

if [[ -f TREE.md ]]; then
    uv run scripts/validate_research.py
else
    echo "No TREE.md — skipping research-integrity gate (not a research project)."
fi
