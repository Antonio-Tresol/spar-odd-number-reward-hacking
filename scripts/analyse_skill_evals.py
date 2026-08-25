#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Aggregate skill-eval JSONL into a summary the research tree can cite.

    uv run scripts/analyse_skill_evals.py results/skill_evals
       -> writes results/skill_evals/summary.json and prints a digest

Trigger family: per-query trigger rate over runs; a should-trigger query passes
at rate > threshold, a should-not-trigger query at rate < threshold (default 0.5,
ties fail both directions — a coin-flip trigger is not reliable either way).
Behaviour family: per task x arm, mean pass rate and per-assertion pass counts.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


def load(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def is_valid_trigger_observation(row: dict[str, Any]) -> bool:
    """A max-turn-capped run still observed the trigger decision; only a run
    that produced no turns at all carries no information. Dropping every
    is_error row silently discarded capped runs — which trigger MORE often
    (invoking the skill consumes turns) — biasing rates downward."""
    return not (row.get("is_error") and row.get("num_turns", 0) == 0)


def analyse_trigger(rows: list[dict[str, Any]], threshold: float) -> dict[str, Any]:
    by_query: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if is_valid_trigger_observation(row):
            by_query[(row["skill"], row["query_idx"])].append(row)
    skills: dict[str, Any] = {}
    for (skill, query_idx), runs in sorted(by_query.items()):
        rate = sum(r["triggered"] for r in runs) / len(runs)
        should = runs[0]["should_trigger"]
        passed = rate > threshold if should else rate < threshold
        entry = skills.setdefault(skill, {"queries": [], "n_pass": 0, "n_fail": 0})
        entry["queries"].append(
            {
                "query_idx": query_idx,
                "query": runs[0]["query"][:90],
                "should_trigger": should,
                "trigger_rate": round(rate, 2),
                "runs": len(runs),
                "passed": passed,
            }
        )
        entry["n_pass" if passed else "n_fail"] += 1
    for entry in skills.values():
        total = entry["n_pass"] + entry["n_fail"]
        entry["pass_rate"] = round(entry["n_pass"] / total, 3) if total else None
        entry["failures"] = [q for q in entry["queries"] if not q["passed"]]
    n_errors = sum(bool(r.get("is_error")) for r in rows)
    return {
        "skills": skills,
        "n_runs": len(rows),
        "n_errored_runs": n_errors,
        "threshold": threshold,
    }


def analyse_behaviour(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_cell: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if not row.get("is_error"):
            by_cell[(row["task"], row["arm"])].append(row)
    tasks: dict[str, Any] = {}
    for (task, arm), runs in sorted(by_cell.items()):
        assertions: dict[str, list[bool]] = defaultdict(list)
        for run in runs:
            for name, grade in run["grades"].items():
                assertions[name].append(bool(grade["passed"]))
        tasks.setdefault(task, {})[arm] = {
            "n_runs": len(runs),
            "mean_pass_rate": round(sum(r["pass_rate"] for r in runs) / len(runs), 3),
            "mean_cost_usd": round(sum(r["cost_usd"] for r in runs) / len(runs), 3),
            "mean_turns": round(sum(r["num_turns"] for r in runs) / len(runs), 1),
            "assertions": {
                name: f"{sum(vals)}/{len(vals)}" for name, vals in sorted(assertions.items())
            },
        }
    n_errors = sum(bool(r.get("is_error")) for r in rows)
    return {"tasks": tasks, "n_runs": len(rows), "n_errored_runs": n_errors}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results_dir", type=Path)
    parser.add_argument("--threshold", type=float, default=0.5)
    args = parser.parse_args()
    summary = {
        "trigger": analyse_trigger(load(args.results_dir / "trigger.jsonl"), args.threshold),
        "behaviour": analyse_behaviour(load(args.results_dir / "behaviour.jsonl")),
    }
    out = args.results_dir / "summary.json"
    out.write_text(json.dumps(summary, indent=2) + "\n")
    for skill, entry in summary["trigger"]["skills"].items():
        print(
            f"trigger  {skill}: {entry['n_pass']}/{entry['n_pass'] + entry['n_fail']} queries pass"
        )
        for failure in entry["failures"]:
            kind = "missed" if failure["should_trigger"] else "false-trigger"
            print(f"  {kind}  rate={failure['trigger_rate']}  {failure['query']}")
    for task, arms in summary["behaviour"]["tasks"].items():
        cells = "  ".join(f"{arm}={info['mean_pass_rate']}" for arm, info in arms.items())
        print(f"behaviour  {task}: {cells}")
    print(f"summary -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
