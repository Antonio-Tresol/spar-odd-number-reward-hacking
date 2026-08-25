#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Mechanical validator for TREE.md and RESEARCH_LOG.md.

Exit 0 = both documents structurally valid; nonzero = violations (printed).
Run from the project root: uv run scripts/validate_research.py
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Final

ROOT: Final[Path] = Path(__file__).resolve().parent.parent
TREE: Final[Path] = ROOT / "TREE.md"
LOG: Final[Path] = ROOT / "RESEARCH_LOG.md"

STATUS_VOCAB: Final[dict[str, set[str]]] = {
    "Q": {"open", "answered", "abandoned"},
    "H": {"open", "supported", "refuted", "abandoned"},
    "E": {"planned", "running", "done", "abandoned"},
    "C": {"unvalidated", "survived", "weakened", "failed"},
}
GRADUATED_CLAIM_STATUSES: Final[frozenset[str]] = frozenset({"survived", "weakened", "failed"})
VALIDATED_CLAIM_STATUSES: Final[frozenset[str]] = frozenset({"survived", "weakened"})
BELIEF_HYPOTHESIS_STATUSES: Final[frozenset[str]] = frozenset({"supported", "refuted"})

NODE_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<indent>\s*)-\s+(?P<id>[QHEC0-9.]+):\s+(?P<text>.*?)"
    r"\s+\[(?P<status>[a-z-]+)\]"
    r"(?:\s*\|\s*evidence:\s*(?P<evidence>[^|]+?))?"
    r"(?:\s*\|\s*log:\s*(?P<log>\d{4}-\d{2}-\d{2}))?\s*$"
)
NODE_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[QHEC]\d+(\.[QHEC]\d+)*$")
NODE_TYPE_RE: Final[re.Pattern[str]] = re.compile(r"([QHEC])\d+$")
SCORECARD_RE: Final[re.Pattern[str]] = re.compile(r"falsif|scorecard|validat", re.IGNORECASE)

LOG_HEADER_RE: Final[re.Pattern[str]] = re.compile(r"^### (\d{4}-\d{2}-\d{2})(?:\s+.*)?$")
LOG_BULLETS: Final[tuple[str, ...]] = (
    "What I did:",
    "What I expected vs what happened:",
    "What this changes about my thinking:",
    "What I will do next:",
)


@dataclass(frozen=True)
class Node:
    """One parsed TREE.md node line."""

    lineno: int
    node_id: str
    node_type: str
    status: str
    evidence: tuple[str, ...]
    log_date: str | None

    @property
    def parent_id(self) -> str | None:
        return self.node_id.rsplit(".", 1)[0] if "." in self.node_id else None

    @property
    def needs_evidence(self) -> bool:
        if self.node_type == "E":
            return self.status == "done"
        return self.node_type == "C" and self.status != "unvalidated"

    @property
    def needs_scorecard(self) -> bool:
        return self.node_type == "C" and self.status in GRADUATED_CLAIM_STATUSES


@dataclass
class Report:
    """Accumulated validation errors."""

    errors: list[str] = field(default_factory=list)

    def add(self, message: str) -> None:
        self.errors.append(message)

    def add_tree(self, lineno: int, message: str) -> None:
        self.errors.append(f"TREE.md:{lineno}: {message}")


def node_type_of(node_id: str) -> str | None:
    """Last letter-prefixed segment determines type: Q1.H2.E1 -> E."""
    match = NODE_TYPE_RE.match(node_id.split(".")[-1])
    return match.group(1) if match else None


def is_node_line(stripped: str) -> bool:
    """True when a list item's first token is shaped like a node ID."""
    if not stripped.startswith("- ") or ":" not in stripped:
        return False
    return bool(NODE_ID_RE.match(stripped[2:].split(":", 1)[0]))


def parse_node(line: str, lineno: int, report: Report) -> Node | None:
    """Parse one node line, reporting grammar and id errors."""
    match = NODE_RE.match(line)
    if match is None:
        report.add_tree(lineno, f"node line does not match grammar: {line.strip()[:80]}")
        return None
    node_id = match["id"]
    ntype = node_type_of(node_id)
    if ntype is None:
        report.add_tree(lineno, f"bad node id {node_id!r}")
        return None
    evidence = tuple(e.strip() for e in (match["evidence"] or "").split(",") if e.strip())
    return Node(lineno, node_id, ntype, match["status"], evidence, match["log"])


def check_lineage(node: Node, seen: set[str], report: Report) -> None:
    """IDs are unique, and every child's parent is defined above it."""
    if node.node_id in seen:
        report.add_tree(node.lineno, f"duplicate id {node.node_id}")
    parent = node.parent_id
    if parent is None:
        if node.node_type != "Q":
            report.add_tree(node.lineno, f"top-level node {node.node_id} must be a question (Q)")
    elif parent not in seen:
        report.add_tree(node.lineno, f"{node.node_id} has no parent {parent} defined above it")


def check_status(node: Node, report: Report) -> None:
    allowed = STATUS_VOCAB[node.node_type]
    if node.status not in allowed:
        report.add_tree(
            node.lineno, f"{node.node_id} status {node.status!r} not in {sorted(allowed)}"
        )


def check_evidence(node: Node, report: Report) -> None:
    """Evidence must be present where required, exist on disk, and — for a
    graduated claim — include a falsification/validation scorecard."""
    if node.needs_evidence and not node.evidence:
        report.add_tree(node.lineno, f"{node.node_id} [{node.status}] requires evidence: <path>")
    for ev in node.evidence:
        if not (ROOT / ev).exists():
            report.add_tree(node.lineno, f"{node.node_id} evidence path does not exist: {ev}")
    if node.needs_scorecard and not any(SCORECARD_RE.search(Path(ev).name) for ev in node.evidence):
        report.add_tree(
            node.lineno,
            f"{node.node_id} [{node.status}] needs a scorecard evidence file "
            "(name containing 'falsify', 'scorecard', or 'validation')",
        )


def check_hypothesis_support(nodes: list[Node], report: Report) -> None:
    """A belief change requires at least one validated child claim."""
    statuses = {n.node_id: n.status for n in nodes}
    for node in nodes:
        if node.node_type != "H" or node.status not in BELIEF_HYPOTHESIS_STATUSES:
            continue
        prefix = f"{node.node_id}."
        has_validated_claim = any(
            nid.startswith(prefix)
            and node_type_of(nid) == "C"
            and status in VALIDATED_CLAIM_STATUSES
            for nid, status in statuses.items()
        )
        if not has_validated_claim:
            report.add(
                f"TREE.md: hypothesis {node.node_id} is [{node.status}] but has no survived/weakened claim"
            )


def validate_tree(report: Report) -> list[Node]:
    if not TREE.exists():
        report.add("TREE.md missing")
        return []
    nodes: list[Node] = []
    seen: set[str] = set()
    in_fence = False
    for lineno, line in enumerate(TREE.read_text().splitlines(), 1):
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence  # fenced examples document the grammar
            continue
        if in_fence or not is_node_line(line.strip()):
            continue
        node = parse_node(line, lineno, report)
        if node is None:
            continue
        check_lineage(node, seen, report)
        check_status(node, report)
        check_evidence(node, report)
        seen.add(node.node_id)
        nodes.append(node)
    check_hypothesis_support(nodes, report)
    return nodes


def split_log_entries(text: str, duplicates: list[str] | None = None) -> dict[str, str]:
    """Split the log into {ISO date: entry body}, preserving file order.

    Repeated dates are recorded in `duplicates` rather than silently overwriting:
    a collapsed entry meant a whole day's content went unvalidated while the run
    still reported success.
    """
    duplicates = duplicates if duplicates is not None else []
    entries: dict[str, str] = {}
    current: str | None = None
    for line in text.splitlines():
        header = LOG_HEADER_RE.match(line)
        if header:
            current = header.group(1)
            if current in entries:
                duplicates.append(current)
            entries[current] = ""
        elif current is not None:
            entries[current] += line + "\n"
    return entries


def check_log_dates(dates: list[str], report: Report) -> None:
    for value in dates:
        try:
            date.fromisoformat(value)
        except ValueError:
            report.add(f"RESEARCH_LOG.md: bad date {value}")
    for earlier, later in zip(dates, dates[1:]):
        if earlier <= later:
            report.add(f"RESEARCH_LOG.md: entries not newest-first ({earlier} then {later})")


def check_log_bullets(entries: dict[str, str], report: Report) -> None:
    """Each entry answers all four questions.

    Emphasis is stripped first: `* **What I did**: ...` puts the colon outside
    the bold, which is the most natural markdown and previously failed.
    """
    for entry_date, body in entries.items():
        plain = body.replace("*", "").replace("_", "")
        for bullet in LOG_BULLETS:
            label = bullet.rstrip(":")
            if not re.search(re.escape(label) + r"\s*:\s*(\S.*)", plain):
                report.add(f"RESEARCH_LOG.md {entry_date}: missing or empty bullet '{bullet}'")


def validate_log(report: Report) -> set[str]:
    """Returns the set of entry dates (ISO strings)."""
    if not LOG.exists():
        report.add("RESEARCH_LOG.md missing")
        return set()
    text = LOG.read_text()
    if "## Project summary" not in text and "## **Project summary**" not in text:
        report.add("RESEARCH_LOG.md: missing '## Project summary' section")
    duplicates: list[str] = []
    entries = split_log_entries(text, duplicates)
    for repeated in duplicates:
        report.add(f"RESEARCH_LOG.md: duplicate entry for {repeated}; merge them")
    dates = list(entries)
    check_log_dates(dates, report)
    check_log_bullets(entries, report)
    return set(dates)


def check_cross_references(nodes: list[Node], log_dates: set[str], report: Report) -> None:
    for node in nodes:
        if node.log_date and node.log_date not in log_dates:
            report.add(f"TREE.md: {node.node_id} references log {node.log_date}, no such entry")


def main() -> int:
    report = Report()
    nodes = validate_tree(report)
    log_dates = validate_log(report)
    check_cross_references(nodes, log_dates, report)
    if report.errors:
        print(f"FAIL — {len(report.errors)} violation(s):")
        for error in report.errors:
            print(f"  - {error}")
        return 1
    print(
        f"OK — TREE.md ({len(nodes)} nodes) and RESEARCH_LOG.md ({len(log_dates)} entries) valid."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
