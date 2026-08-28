#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Layer 4 (interface): how the record is shown on a terminal.

Every read-only command's rendering lives here — the tree outline, one node's
full detail, a lineage path, search hits, the evidence table, orphaned notes,
the JSON representation, and the Mermaid diagram — together with the small
formatting helpers they share. Nothing in this module writes to the record or
decides whether it is valid; it turns a loaded graph into lines of text.

Keeping it separate from `research_graph.py` leaves that file as the command
registry and dispatch, so adding a command means declaring it in one table
rather than editing a file that also knows how to draw tables.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Final

_HERE: Final[str] = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import research_graph_checks as checks  # noqa: E402
import research_graph_model as model  # noqa: E402
from research_graph_model import OK as EXIT_OK  # noqa: E402
from research_graph_model import USAGE as EXIT_USAGE  # noqa: E402

LINE_WIDTH: Final[int] = 80


# Shared formatting and lookup helpers, used by more than one handler below.


def _truncate(text: str, width: int = LINE_WIDTH) -> str:
    """Collapse whitespace and shorten text to width characters for a scannable line."""
    flat = " ".join(text.split())
    return flat if len(flat) <= width else flat[: width - 3] + "..."


def _excerpt(text: str, term: str, width: int = LINE_WIDTH) -> str:
    """A short window of text centred on the first case-insensitive hit of term."""
    flat = " ".join(text.split())
    idx = flat.lower().find(term.lower())
    if idx == -1:
        return _truncate(flat, width)
    start = max(0, idx - width // 2)
    end = min(len(flat), start + width)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(flat) else ""
    return f"{prefix}{flat[start:end]}{suffix}"


def _node_line(node: model.GraphNode, indent: int = 0) -> str:
    """One line matching TREE.md's own grammar: '<id>: <text> [<status>]'."""
    return f"{'  ' * indent}{node.node_id}: {_truncate(node.text)} [{node.status}]"


def _sorted_nodes(graph: model.Graph) -> list[model.GraphNode]:
    """Nodes in the order they appear in TREE.md, the order agents expect to read them."""
    return sorted(graph.nodes.values(), key=lambda n: n.lineno)


def _require_node(graph: model.Graph, node_id: str) -> model.GraphNode | None:
    """Look up node_id, printing a plain-language error if it is not in the record."""
    node = graph.nodes.get(node_id)
    if node is None:
        print(
            f"Error: no node with id {node_id!r} in the record. "
            "Run 'tree' to see the ids that exist.",
            file=sys.stderr,
        )
    return node


def _pin_and_drift(root: Path, graph: model.Graph) -> tuple[set[str], set[str]]:
    """Evidence paths with a recorded hash, and which of those have changed since.

    An unpinned path was never drift-checked, so callers report it as "not
    pinned", never as "no drift" — those are different claims."""
    pinned: set[str] = set()
    for provenance in checks.read_pins(root, graph).values():
        pinned.update(provenance.get("evidence_sha256", {}))
    findings = checks.drift_report(root, graph)
    drifted = {path for path in pinned if any(path in finding for finding in findings)}
    return pinned, drifted


def _evidence_rows(
    nodes: list[model.GraphNode], graph: model.Graph, pinned: set[str], drifted: set[str]
) -> list[tuple[str, ...]]:
    """(node id, path, kind, exists, pinned, drifted) for every evidence path on nodes."""
    rows: list[tuple[str, ...]] = []
    for node in nodes:
        for path in node.evidence:
            artifact = graph.artifacts[path]
            is_pinned = path in pinned
            drift = "n/a" if not is_pinned else ("yes" if path in drifted else "no")
            exists = "yes" if artifact.exists else "no"
            pin = "yes" if is_pinned else "no"
            rows.append((node.node_id, path, artifact.kind, exists, pin, drift))
    return rows


def _print_table(headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> None:
    """Print a header row then one '|'-separated row per data row."""
    print(" | ".join(headers))
    for row in rows:
        print(" | ".join(row))


# Navigation commands: implemented directly against the loaded graph.


def cmd_tree(args: argparse.Namespace) -> int:
    graph = model.load(args.root)
    nodes = _sorted_nodes(graph)
    if args.type:
        nodes = [n for n in nodes if n.node_type == args.type]
    if args.status:
        nodes = [n for n in nodes if n.status == args.status]
    if args.under:
        nodes = [
            n for n in nodes if n.node_id == args.under or n.node_id.startswith(args.under + ".")
        ]
    if not nodes:
        print("No nodes match those filters.")
        return EXIT_OK
    for node in nodes:
        print(_node_line(node, indent=node.node_id.count(".")))
    return EXIT_OK


def cmd_show(args: argparse.Namespace) -> int:
    graph = model.load(args.root)
    node = _require_node(graph, args.id)
    if node is None:
        return EXIT_USAGE
    print(f"{node.node_id} ({node.node_type})")
    print(f"  status: {node.status}")
    print(f"  text: {node.text}")
    print(f"  parent: {node.parent or '(none - top-level question)'}")
    print(f"  children: {', '.join(node.children) or '(none)'}")
    print(f"  log: {node.log_date or '(none)'}")
    pinned, drifted = _pin_and_drift(args.root, graph)
    rows = _evidence_rows([node], graph, pinned, drifted)
    print("Evidence:")
    if not rows:
        print("  none recorded.")
    for _, path, kind, exists, pin, drift in rows:
        print(f"  {path}  kind={kind} exists={exists} pinned={pin} drifted={drift}")
    log_hits = sorted(d for d, e in graph.entries.items() if node.node_id in e.mentions_ids)
    print(f"Mentioned in log entries: {', '.join(log_hits) or '(none)'}")
    doc_hits = sorted(
        p
        for p, d in graph.documents.items()
        if node.node_id in d.linked_from or node.node_id in d.mentions_ids
    )
    print(f"Mentioned in documents: {', '.join(doc_hits) or '(none)'}")
    return EXIT_OK


def cmd_path(args: argparse.Namespace) -> int:
    graph = model.load(args.root)
    node = _require_node(graph, args.id)
    if node is None:
        return EXIT_USAGE
    chain = [node]
    while chain[-1].parent is not None:
        parent = graph.nodes.get(chain[-1].parent)
        if parent is None:
            break
        chain.append(parent)
    for step in reversed(chain):
        print(_node_line(step))
    return EXIT_OK


def cmd_search(args: argparse.Namespace) -> int:
    graph = model.load(args.root)
    term = args.term
    hits = 0
    for node in _sorted_nodes(graph):
        if term.lower() in node.text.lower():
            print(f"node {node.node_id}: {_excerpt(node.text, term)}")
            hits += 1
    for date in sorted(graph.entries, reverse=True):
        entry = graph.entries[date]
        if term.lower() in entry.body.lower():
            print(f"log {date}: {_excerpt(entry.body, term)}")
            hits += 1
    for path in sorted(graph.documents):
        doc = graph.documents[path]
        if term.lower() in doc.title.lower() or term.lower() in path.lower():
            print(f"document {path}: {doc.title}")
            hits += 1
    if hits == 0:
        print(f"No hits for {term!r}.")
    return EXIT_OK


def cmd_evidence(args: argparse.Namespace) -> int:
    graph = model.load(args.root)
    if args.id:
        node = _require_node(graph, args.id)
        if node is None:
            return EXIT_USAGE
        nodes = [node]
    else:
        nodes = _sorted_nodes(graph)
    if args.graduated:
        nodes = [n for n in nodes if n.status in checks.GRADUATED]
    pinned, drifted = _pin_and_drift(args.root, graph)
    rows = _evidence_rows(nodes, graph, pinned, drifted)
    if not rows:
        print("No evidence found for that selection.")
        return EXIT_OK
    _print_table(("node", "path", "kind", "exists", "pinned", "drifted"), rows)
    return EXIT_OK


def cmd_orphans(args: argparse.Namespace) -> int:
    graph = model.load(args.root)
    findings = checks.orphan_report(graph)
    if not findings:
        print("No orphan documents found.")
        return EXIT_OK
    for finding in findings:
        print(finding)
    return EXIT_OK


def cmd_json(args: argparse.Namespace) -> int:
    graph = model.load(args.root)
    text = json.dumps(model.to_ir(graph), indent=2)
    if args.out:
        args.out.write_text(text + "\n")
        print(f"Wrote the JSON IR to {args.out}.")
    else:
        print(text)
    return EXIT_OK


def cmd_mermaid(args: argparse.Namespace) -> int:
    graph = model.load(args.root)
    text = model.to_mermaid(graph, with_evidence=args.evidence)
    if args.out:
        args.out.write_text(text + "\n")
        print(f"Wrote the Mermaid diagram to {args.out}.")
    else:
        print(text)
    return EXIT_OK
