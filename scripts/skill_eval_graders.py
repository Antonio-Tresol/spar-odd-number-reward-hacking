"""Mechanical graders for the behaviour evals (split from run_skill_evals.py).

Each grader maps (workspace, grader_config, judge_model) -> {assertion: {passed,
evidence}}. Kept separate so the runner stays under the size gate and the
graders remain individually testable.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Final

CLAIM_RE: Final[re.Pattern[str]] = re.compile(
    r"<!--\s*claim:\s*(?P<value>-?[\d.]+(?:[eE][-+]?\d+)?)\s+from\s+"
    r"(?P<path>[^\s#]+)(?:#(?P<key>\S+))?(?:\s+tol=(?P<tol>[\d.eE+-]+))?\s*-->"
)


# --------------------------------------------------------------------------- graders
Grade = dict[str, dict[str, Any]]


def grade_canary_presence(workspace: Path, config: dict[str, Any], judge_model: str) -> Grade:
    artefact = workspace / config["artefact"]
    if not artefact.is_file():
        return {
            "artefact_exists": {"passed": False, "evidence": f"{config['artefact']} not written"}
        }
    text = artefact.read_text()
    grade: Grade = {"artefact_exists": {"passed": True, "evidence": f"{len(text)} chars"}}
    for source, tokens in config["canaries"].items():
        hits = [t for t in tokens if t in text]
        grade[f"canary:{source}"] = {
            "passed": len(hits) == len(tokens),
            "evidence": f"found {hits or 'none'} of {tokens}",
        }
    return grade


def grade_tree_validates(workspace: Path, config: dict[str, Any], judge_model: str) -> Grade:
    done = subprocess.run(
        [sys.executable, "scripts/validate_research.py"],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    return {
        "tree_validates": {
            "passed": done.returncode == 0,
            "evidence": (done.stdout.strip() or done.stderr.strip())[:400],
        }
    }


def grade_report_verdict_judge(workspace: Path, config: dict[str, Any], judge_model: str) -> Grade:
    artefact = workspace / config["artefact"]
    if not artefact.is_file():
        return {"report_exists": {"passed": False, "evidence": f"{config['artefact']} not written"}}
    prompt = (
        f"{config['judge_question']}\n\nReport:\n---\n{artefact.read_text()[:6000]}\n---\n\n"
        'Answer with ONLY a JSON object: {"claims_effect": true/false, "reports_null": true/false, '
        '"quote": "<the sentence that decides it>"}'
    )
    from run_skill_evals import run_claude  # runner import, deferred to avoid a cycle

    result = run_claude(prompt, workspace, judge_model, max_turns=1, timeout=120)
    match = re.search(r"\{.*\}", result.result_text, re.DOTALL)
    if match is None:
        return {
            "reports_null": {
                "passed": False,
                "evidence": f"judge unparseable: {result.result_text[:200]}",
            }
        }
    verdict = json.loads(match.group(0))
    return {
        "report_exists": {"passed": True, "evidence": ""},
        "reports_null": {
            "passed": bool(verdict.get("reports_null")) and not verdict.get("claims_effect"),
            "evidence": str(verdict.get("quote", ""))[:300],
        },
    }


def _bucket(item_id: str, mod: int) -> int:
    return int(hashlib.md5(item_id.encode(), usedforsecurity=False).hexdigest(), 16) % mod


def _rows_from_json_text(text: str) -> list[dict[str, Any]]:
    """Result rows from JSONL lines, a JSON array, or {'results': [...]}."""
    found: list[dict[str, Any]] = []
    for chunk in text.splitlines():
        try:
            parsed = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        found.extend(
            r for r in (parsed if isinstance(parsed, list) else [parsed]) if isinstance(r, dict)
        )
    if not found:
        try:
            whole = json.loads(text)
            candidates = whole if isinstance(whole, list) else whole.get("results", [])
            found.extend(r for r in candidates if isinstance(r, dict))
        except (json.JSONDecodeError, AttributeError):
            pass
    return found


def collect_result_rows(workspace: Path, items: set[str]) -> dict[str, dict[str, Any]]:
    """First recorded row per known item id, across every structured file in results/.

    CSV is accepted alongside JSON: coverage and error-handling are gradeable
    even when the format deviates from the skill's JSONL convention (typical of
    no-skill arms).
    """
    rows: dict[str, dict[str, Any]] = {}
    results_dir = workspace / "results"
    for path in sorted(results_dir.rglob("*")) if results_dir.is_dir() else []:
        if path.suffix not in {".json", ".jsonl", ".csv"} or not path.is_file():
            continue
        parsed = (
            [dict(r) for r in csv.DictReader(path.open())]
            if path.suffix == ".csv"
            else _rows_from_json_text(path.read_text())
        )
        for row in parsed:
            if row.get("item_id") in items:
                rows.setdefault(str(row["item_id"]), row)
    return rows


def grade_observability(workspace: Path, config: dict[str, Any], judge_model: str) -> Grade:
    items = [row["item_id"] for row in csv.DictReader((workspace / "items.csv").open())]
    permanent = {i for i in items if _bucket(i, 50) == 7}
    transient = {i for i in items if _bucket(i, 10) == 3} - permanent
    rows = collect_result_rows(workspace, set(items))

    def is_error_row(row: dict[str, Any]) -> bool:
        return bool(row.get("error")) or str(row.get("status", "")).lower() in {"error", "failed"}

    successes = {i for i, row in rows.items() if not is_error_row(row)}
    transient_ok = len(transient & successes)
    permanent_recorded = len(permanent & set(rows))
    return {
        "structured_results": {
            "passed": len(rows) >= 150,
            "evidence": f"{len(rows)}/{len(items)} items found in results/",
        },
        "full_coverage": {
            "passed": len(rows) >= len(items) - 1,
            "evidence": f"{len(rows)}/{len(items)} rows (failures should be rows too)",
        },
        "permanent_failures_recorded": {
            "passed": permanent_recorded >= max(1, len(permanent) - 1),
            "evidence": f"{permanent_recorded}/{len(permanent)} permanent-failure items present",
        },
        "transient_retried": {
            "passed": transient_ok >= int(0.8 * len(transient)),
            "evidence": f"{transient_ok}/{len(transient)} transient items ended as successes",
        },
    }


def resolve_source_key(source: Any, key: str) -> Any:
    """Dotted lookup into the source JSON; `ci_delta.0` indexes into a list.

    Agents naturally write `#bootstrap_ci_delta.0` for the lower CI bound; the
    flat .get() treated that as an unknown key and false-failed a correct report.
    """
    value = source
    for part in key.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return None
    return None if isinstance(value, (dict, list)) else value


def grade_provenance_markers(workspace: Path, config: dict[str, Any], judge_model: str) -> Grade:
    artefact = workspace / config["artefact"]
    if not artefact.is_file():
        return {"report_exists": {"passed": False, "evidence": f"{config['artefact']} not written"}}
    text = artefact.read_text()
    source = json.loads((workspace / config["source"]).read_text())
    markers = list(CLAIM_RE.finditer(text))
    resolved = 0
    for marker in markers:
        expected = resolve_source_key(source, marker["key"] or "")
        if expected is None:
            continue
        tolerance = float(marker["tol"] or 0.005)
        try:
            if abs(float(marker["value"]) - float(expected)) <= tolerance:
                resolved += 1
        except (TypeError, ValueError):
            continue
    anchored_stats = [
        s
        for s in config["key_stats"]
        if s in text and any(m["value"].startswith(s) for m in markers)
    ]
    return {
        "report_exists": {"passed": True, "evidence": ""},
        "markers_present": {
            "passed": len(markers) >= 2,
            "evidence": f"{len(markers)} claim markers",
        },
        "markers_resolve": {
            "passed": len(markers) > 0 and resolved == len(markers),
            "evidence": f"{resolved}/{len(markers)} markers match {config['source']}",
        },
        "key_stats_anchored": {
            "passed": len(anchored_stats) == len(config["key_stats"]),
            "evidence": f"anchored {anchored_stats} of {config['key_stats']}",
        },
    }


GRADERS: Final[dict[str, Callable[[Path, dict[str, Any], str], Grade]]] = {
    "canary_presence": grade_canary_presence,
    "tree_validates": grade_tree_validates,
    "report_verdict_judge": grade_report_verdict_judge,
    "observability_results": grade_observability,
    "provenance_markers": grade_provenance_markers,
}
