#!/usr/bin/env bash
# Every mechanical check, in one command.
#
#   lanorme  — code quality, Agent Skills spec compliance, and the harness's own
#              plugins (tensors, skill_portability, provenance). PYTHONPATH=. is
#              what lets lanorme import them from lanorme_plugins/.
#   pytest   — the checks' own tests, including a false-positive suite. A checker
#              that cries wolf gets bypassed, so quiet-on-clean-input is tested
#              as carefully as fires-on-bad-input.
#   research gate — validate_research.py, run through research_graph.py verify
#              where that CLI exists (same validator, plus evidence drift
#              against recorded evidence hashes and orphaned notes/). Deliberately
#              standalone and dependency-free: a project that never installs
#              lanorme must still have every integrity guarantee. Skipped in
#              the harness repo itself, which is not a research project and
#              has no TREE.md.
set -euo pipefail
cd "$(dirname "$0")"

# Formatting and lint, one statement each: joined with `&&`, a format
# failure would abort nothing (under `set -e` only the command after the
# final `&&` counts) and would skip the lint entirely (issue #4). The
# version is pinned to match ruff.toml's required-version, and rule
# selection lives in ruff.toml, where a project can extend it.
uvx ruff@0.15.8 format --check .
uvx ruff@0.15.8 check .

PYTHONPATH=. uvx lanorme check "${1:-.}"

if [[ -d tests ]]; then
    uv run --python 3.13 --with pytest --with lanorme pytest tests -q
fi

if [[ -f TREE.md ]]; then
    if [[ -f scripts/research_graph.py ]]; then
        uv run scripts/research_graph.py verify
    else
        uv run scripts/validate_research.py
    fi
else
    echo "No TREE.md — skipping research-integrity gate (not a research project)."
fi
