#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Run trigger and behaviour evals for the harness skills via headless Claude Code.

Two families:

  trigger    Does the skill load on realistic prompts? Labelled queries from each
             skill's evals/trigger_queries.json; detection = a Skill tool call in
             the stream-json transcript.
  behaviour  Does the loaded skill change behaviour? Three arms per task — the
             real skill, a length-matched placebo installed under the SAME skill
             name (so prompts are byte-identical), and no skill. Grading is
             mechanical wherever the fixtures plant ground truth.

Every run gets an isolated workspace; `--setting-sources project` keeps the
user's global skills and MCP servers out of the experiment. Results append to a
JSONL keyed by (family, skill/task, query/arm, run); re-running skips completed
keys, so a killed sweep resumes where it stopped.

Examples:
    uv run scripts/run_skill_evals.py trigger --runs 3
    uv run scripts/run_skill_evals.py behaviour --tasks fabrication-canary --arms skill,none --runs 1
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

HARNESS: Final[Path] = Path(__file__).resolve().parent.parent
SKILLS_DIR: Final[Path] = HARNESS / ".claude" / "skills"
BEHAVIOUR_DIR: Final[Path] = HARNESS / "evals" / "behaviour"
TRIGGER_SKILLS: Final[tuple[str, ...]] = (
    "derive-from-sources",
    "experiment-engineering",
    "research-log",
    "validate-claims",
)
ARMS: Final[tuple[str, ...]] = ("skill", "placebo", "none")
CLAIM_RE: Final[re.Pattern[str]] = re.compile(
    r"<!--\s*claim:\s*(?P<value>-?[\d.]+(?:[eE][-+]?\d+)?)\s+from\s+"
    r"(?P<path>[^\s#]+)(?:#(?P<key>\S+))?(?:\s+tol=(?P<tol>[\d.eE+-]+))?\s*-->"
)

log = logging.getLogger("skill-evals")


# --------------------------------------------------------------------------- claude
@dataclass
class RunResult:
    """Parsed outcome of one headless Claude Code run."""

    skills_invoked: list[str]
    result_text: str
    num_turns: int
    duration_ms: int
    cost_usd: float
    is_error: bool
    error: str | None = None
    subtype: str = ""


def run_claude(
    prompt: str, cwd: Path, model: str, max_turns: int, timeout: int, transcript: Path | None = None
) -> RunResult:
    cmd = [
        "claude",
        "-p",
        prompt,
        "--output-format",
        "stream-json",
        "--verbose",
        "--model",
        model,
        "--max-turns",
        str(max_turns),
        "--setting-sources",
        "project",
        "--dangerously-skip-permissions",
    ]
    try:
        done = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired as exc:
        if transcript is not None and exc.stdout:
            out = exc.stdout if isinstance(exc.stdout, str) else exc.stdout.decode(errors="replace")
            transcript.write_text(out)
        return RunResult([], "", 0, timeout * 1000, 0.0, True, f"timeout after {timeout}s")
    if transcript is not None:
        # The transcript is the only way to diagnose WHY a run behaved as it
        # did; discarding it made every failure analysis a re-run.
        transcript.write_text(done.stdout)
    skills, final = parse_stream(done.stdout)
    if "hit your session limit" in done.stdout or "usage limit" in done.stdout.lower():
        # The CLI reports a usage-limit kill as an ordinary assistant message
        # with subtype=success; 41 such runs were once recorded as real data.
        return RunResult(
            skills,
            "",
            int(final.get("num_turns", 0)),
            0,
            0.0,
            True,
            "usage limit hit",
            "usage_limit",
        )
    is_err = bool(final.get("is_error", done.returncode != 0))
    return RunResult(
        skills_invoked=skills,
        result_text=str(final.get("result", "")),
        num_turns=int(final.get("num_turns", 0)),
        duration_ms=int(final.get("duration_ms", 0)),
        cost_usd=float(final.get("total_cost_usd") or 0.0),
        is_error=is_err,
        error=done.stderr.strip()[:500] if is_err else None,
        subtype=str(final.get("subtype", "")),
    )


def parse_stream(stdout: str) -> tuple[list[str], dict[str, Any]]:
    """Skill invocations and the final result event from a stream-json transcript."""
    skills: list[str] = []
    final: dict[str, Any] = {}
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "assistant":
            for block in event.get("message", {}).get("content", []):
                if block.get("type") == "tool_use" and block.get("name") == "Skill":
                    skills.append(str(block.get("input", {}).get("skill", "")))
        elif event.get("type") == "result":
            final = event
    return skills, final


# --------------------------------------------------------------------------- workspaces
def make_workspace(key: str) -> Path:
    """A fenced workspace OUTSIDE any git repository.

    The original layout nested workspaces inside the host project. Eval agents
    given research-flavoured prompts ("fix statuses before I commit") walked up
    to the enclosing repo and wrote fabricated research state into the real
    TREE.md — the containment incident of 2026-07-20. Two fences now: the
    workspace lives under the OS temp dir, and it is its own git repo so any
    upward repo discovery stops at the workspace boundary.
    """
    workspace = Path(tempfile.gettempdir()) / "skill-eval-workspaces" / key
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    subprocess.run(
        ["git", "init", "-q"], cwd=workspace, capture_output=True, check=False, timeout=15
    )
    return workspace


def install_skill(workspace: Path, name: str, arm: str) -> None:
    """Install the real skill or the placebo under the same name; none installs nothing."""
    if arm == "none":
        return
    dest = workspace / ".claude" / "skills" / name
    dest.mkdir(parents=True)
    source = SKILLS_DIR / name
    if arm == "skill":
        for item in source.iterdir():
            if item.name == "evals":
                continue
            (shutil.copytree if item.is_dir() else shutil.copy2)(item, dest / item.name)
        return
    description = re.search(
        r"^description:.*?(?=^[a-z-]+:|^---$)",
        (source / "SKILL.md").read_text(),
        re.MULTILINE | re.DOTALL,
    )
    body = (BEHAVIOUR_DIR / "placebo_body.md").read_text()
    (dest / "SKILL.md").write_text(
        f"---\nname: {name}\n{description.group(0).strip()}\n---\n\n{body}"
    )


def build_behaviour_workspace(task: dict[str, Any], arm: str, key: str) -> Path:
    workspace = make_workspace(key)
    for dest_rel, src_rel in task.get("fixtures", {}).items():
        dest = workspace / dest_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(BEHAVIOUR_DIR / src_rel, dest)
    if task.get("research_scaffold"):
        (workspace / "scripts").mkdir(exist_ok=True)
        shutil.copy2(
            HARNESS / "scripts" / "validate_research.py",
            workspace / "scripts" / "validate_research.py",
        )
        (workspace / "TREE.md").write_text(
            "# Research tree\n\nGrammar: `- <ID>: <text> [<status>]` optionally "
            "`| evidence: <path>` and `| log: YYYY-MM-DD`. Statuses — Q: open/answered/abandoned; "
            "H: open/supported/refuted/abandoned; E: planned/running/done/abandoned; "
            "C: unvalidated/survived/weakened/failed. Claims may only graduate past unvalidated "
            "with a falsification/validation scorecard linked as evidence. "
            "Validate with `uv run scripts/validate_research.py`.\n\n"
            "- Q1: Does the new prompting method (group B) improve scores over control? [open]\n"
            "  - Q1.H1: Group B scores higher than group A [open]\n"
            "    - Q1.H1.E1: Pilot, 200 items, results/pilot_data.csv [running]\n"
        )
        (workspace / "RESEARCH_LOG.md").write_text(
            "# Pilot — research log\n\n## Project summary\n\nPilot of the new prompting method.\n\n"
            "### 2026-07-19\n\n* What I did: collected the pilot data (results/pilot_data.csv).\n"
            "* What I expected vs what happened: collection was uneventful.\n"
            "* What this changes about my thinking: nothing yet; analysis pending.\n"
            "* What I will do next: analyse the pilot and record the outcome.\n"
        )
    install_skill(workspace, task["skill"], arm)
    return workspace


def build_trigger_workspace(skill: str, key: str, workspace_files: dict[str, str]) -> Path:
    """Trigger workspaces contain the files the queries mention: a query about a
    missing file makes the agent stop and ask, which reads as a non-trigger and
    confounds the measurement."""
    workspace = make_workspace(key)
    for rel, content in workspace_files.items():
        target = workspace / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    install_skill(workspace, skill, "skill")
    return workspace


from skill_eval_graders import GRADERS, Grade  # noqa: E402 — sibling module, script-style import


# --------------------------------------------------------------------------- families
def load_done_keys(out_file: Path) -> set[str]:
    if not out_file.is_file():
        return set()
    return {json.loads(line)["key"] for line in out_file.read_text().splitlines() if line.strip()}


def append_row(out_file: Path, row: dict[str, Any]) -> None:
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with out_file.open("a") as sink:
        sink.write(json.dumps(row) + "\n")


class Progress:
    """ETA logging for a sweep of known size."""

    def __init__(self, total: int) -> None:
        self.total, self.done, self.start = total, 0, time.monotonic()

    def tick(self, label: str, cost: float) -> None:
        self.done += 1
        elapsed = time.monotonic() - self.start
        rate = elapsed / self.done
        remaining = (self.total - self.done) * rate
        log.info(
            "%d/%d done (%s) — %.0fs/run, ETA %dm%02ds, cost so far incl. this run $%.3f",
            self.done,
            self.total,
            label,
            rate,
            remaining // 60,
            remaining % 60,
            cost,
        )


def cmd_trigger(args: argparse.Namespace) -> None:
    out_file = args.out / "trigger.jsonl"
    done_keys = load_done_keys(out_file)
    jobs = []
    files_by_skill: dict[str, dict[str, str]] = {}
    for skill in args.skills:
        spec = json.loads((SKILLS_DIR / skill / "evals" / "trigger_queries.json").read_text())
        files_by_skill[skill] = spec.get("workspace_files", {})
        for query_idx, query in enumerate(spec["queries"]):
            for run_idx in range(args.runs):
                jobs.append((skill, query_idx, query, run_idx))
    jobs = [j for j in jobs if f"trigger|{j[0]}|q{j[1]:02d}|r{j[3]}" not in done_keys]
    progress, total_cost = Progress(len(jobs)), 0.0
    log.info("trigger: %d runs to do (%d already recorded)", len(jobs), len(done_keys))
    for skill, query_idx, query, run_idx in jobs:
        key = f"trigger|{skill}|q{query_idx:02d}|r{run_idx}"
        workspace = build_trigger_workspace(skill, key.replace("|", "_"), files_by_skill[skill])
        result = run_claude(
            query["query"],
            workspace,
            args.model,
            max_turns=4,
            timeout=300,
            transcript=workspace / ".transcript.jsonl",
        )
        if result.subtype == "usage_limit":
            log.warning("usage limit hit at %s — aborting sweep; re-run to resume after reset", key)
            return
        total_cost += result.cost_usd
        append_row(
            out_file,
            {
                "key": key,
                "family": "trigger",
                "skill": skill,
                "query_idx": query_idx,
                "query": query["query"],
                "should_trigger": query["should_trigger"],
                "run": run_idx,
                "triggered": skill in result.skills_invoked,
                "skills_invoked": result.skills_invoked,
                "num_turns": result.num_turns,
                "cost_usd": result.cost_usd,
                "is_error": result.is_error,
                "error": result.error,
                "subtype": result.subtype,
                "workspace": str(workspace),
                "ts": time.strftime("%FT%T"),
            },
        )
        progress.tick(key, total_cost)


def cmd_behaviour(args: argparse.Namespace) -> None:
    out_file = args.out / "behaviour.jsonl"
    done_keys = load_done_keys(out_file)
    tasks = {t["id"]: t for t in json.loads((BEHAVIOUR_DIR / "tasks.json").read_text())["tasks"]}
    jobs = [
        (tasks[t], arm, run_idx)
        for t in args.tasks
        for arm in args.arms
        for run_idx in range(args.runs)
        if f"behaviour|{t}|{arm}|r{run_idx}" not in done_keys
    ]
    progress, total_cost = Progress(len(jobs)), 0.0
    log.info("behaviour: %d runs to do (%d already recorded)", len(jobs), len(done_keys))
    for task, arm, run_idx in jobs:
        key = f"behaviour|{task['id']}|{arm}|r{run_idx}"
        workspace = build_behaviour_workspace(task, arm, key.replace("|", "_"))
        prompt = (
            task["prompt"]
            if arm == "none"
            else (
                f"{task['prompt']}\n\nBefore starting, read .claude/skills/{task['skill']}/SKILL.md "
                "and follow its instructions."
            )
        )
        result = run_claude(
            prompt,
            workspace,
            args.model,
            task["max_turns"],
            timeout=args.timeout,
            transcript=workspace / ".transcript.jsonl",
        )
        if result.subtype == "usage_limit":
            log.warning("usage limit hit at %s — aborting sweep; re-run to resume after reset", key)
            return
        total_cost += result.cost_usd
        grades: Grade = {}
        for grader_name in task["graders"]:
            try:
                grades.update(
                    GRADERS[grader_name](workspace, task.get("grader_config", {}), args.judge_model)
                )
            except Exception as exc:  # noqa: BLE001 — a grader crash is a recorded outcome, not a sweep abort
                grades[grader_name] = {"passed": False, "evidence": f"grader crashed: {exc!r}"}
        append_row(
            out_file,
            {
                "key": key,
                "family": "behaviour",
                "task": task["id"],
                "skill": task["skill"],
                "arm": arm,
                "run": run_idx,
                "grades": grades,
                "pass_rate": round(
                    sum(g["passed"] for g in grades.values()) / max(1, len(grades)), 3
                ),
                "num_turns": result.num_turns,
                "duration_ms": result.duration_ms,
                "cost_usd": result.cost_usd,
                "is_error": result.is_error,
                "error": result.error,
                "subtype": result.subtype,
                "workspace": str(workspace),
                "ts": time.strftime("%FT%T"),
            },
        )
        progress.tick(key, total_cost)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="family", required=True)
    trigger = sub.add_parser("trigger", help="skill-triggering evals")
    trigger.add_argument("--skills", type=lambda s: s.split(","), default=list(TRIGGER_SKILLS))
    trigger.add_argument("--model", default="haiku")
    trigger.add_argument("--runs", type=int, default=3)
    behaviour = sub.add_parser("behaviour", help="three-arm behaviour probes")
    behaviour.add_argument(
        "--tasks",
        type=lambda s: s.split(","),
        default=["fabrication-canary", "null-honesty", "observability", "provenance"],
    )
    behaviour.add_argument("--arms", type=lambda s: s.split(","), default=list(ARMS))
    behaviour.add_argument("--model", default="sonnet")
    behaviour.add_argument("--judge-model", default="haiku")
    behaviour.add_argument("--runs", type=int, default=3)
    behaviour.add_argument("--timeout", type=int, default=1200)
    for p in (trigger, behaviour):
        p.add_argument("--out", type=Path, default=Path("results/skill_evals"))
    args = parser.parse_args()
    args.out = args.out.resolve()
    log_file = args.out / "run.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(log_file)],
    )
    log.info("family=%s out=%s argv=%s", args.family, args.out, sys.argv[1:])
    (cmd_trigger if args.family == "trigger" else cmd_behaviour)(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
