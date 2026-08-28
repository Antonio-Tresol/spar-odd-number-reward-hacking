# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Domain model and repository for the research record, layers one and two.

Layer one is the domain model: frozen dataclasses for the four things the
record contains (tree nodes, log entries, notes documents, evidence
artifacts) and pure functions over them — working out what kind of thing an
evidence path points at, building the JSON description machines read, and
drawing the mermaid diagram people look at.

Layer two is the repository: `load` is the one place in the whole system
that reads the record from disk, and `scripts/validate_research.py` stays
the single authority on the grammar, so every parsing rule is imported from
it and none is written twice.

THE RECORD IS THE DATABASE — markdown is the canonical store, parsed fresh
on every read; nothing else is ever a source of truth.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

# The sibling validator is a plain script rather than an installed package,
# so its own directory has to be importable before we can import it.
_SCRIPTS_DIRECTORY: Final[Path] = Path(__file__).resolve().parent
if str(_SCRIPTS_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIRECTORY))

import validate_research as grammar  # noqa: E402

IR_VERSION: Final[int] = 1

# Exit codes every module in this system returns, so the meaning of a number
# is decided once: 0 means the command succeeded, 1 means the record is
# invalid or a check failed, 2 means the command was used wrongly.
OK: Final[int] = 0
INVALID: Final[int] = 1
USAGE: Final[int] = 2

# A finding is one plain sentence about the record, starting with how serious
# it is. Errors mean the record is wrong, warnings mean it deserves a look,
# and information is context that never fails a run.
Finding = str
ERROR: Final[str] = "ERROR: "
WARNING: Final[str] = "WARNING: "
INFO: Final[str] = "INFO: "

TREE_FILE: Final[str] = "TREE.md"
LOG_FILE: Final[str] = "RESEARCH_LOG.md"
NOTES_PATTERN: Final[str] = "notes/**/*.md"

# The long name for each node id letter, so callers never handle raw letters.
NODE_TYPE_NAMES: Final[dict[str, str]] = {
    "Q": "question",
    "H": "hypothesis",
    "E": "experiment",
    "C": "claim",
}

# A node id as it appears inside ordinary prose, such as a log entry that says
# "Q1.H2.E1 finished". Matches are kept only when that node really exists.
MENTION_ID_RE: Final[re.Pattern[str]] = re.compile(r"\b[QHEC]\d+(?:\.[QHEC]\d+)*\b")

# ---------------------------------------------------------------------------
# Layer one: the domain model — frozen data and pure functions over it.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Artifact:
    """One evidence path, and who in the tree points at it."""

    path: str
    kind: str
    exists: bool
    referenced_by: tuple[str, ...]


@dataclass(frozen=True)
class GraphNode:
    """One TREE.md node, wired to the node above it and the nodes below it.

    Children are listed by rising id, which puts a claim before the
    experiments under the same hypothesis. Anything that shows the tree to a
    reader should sort them by `lineno` instead, to keep the file's own order.
    """

    node_id: str
    node_type: str
    text: str
    status: str
    evidence: tuple[str, ...]
    log_date: str | None
    lineno: int
    parent: str | None
    children: tuple[str, ...]


@dataclass(frozen=True)
class LogEntry:
    """One dated RESEARCH_LOG.md entry and what it refers to."""

    date: str
    body: str
    mentions_ids: tuple[str, ...]
    mentions_paths: tuple[str, ...]


@dataclass(frozen=True)
class Document:
    """One notes document, and whether anything in the record reaches it."""

    path: str
    title: str
    linked_from: tuple[str, ...]
    mentions_ids: tuple[str, ...]
    mentions_paths: tuple[str, ...]
    orphan: bool


@dataclass(frozen=True)
class Graph:
    """The whole research record, read once and held in memory as one value."""

    root: Path
    nodes: dict[str, GraphNode]
    entries: dict[str, LogEntry]
    documents: dict[str, Document]
    artifacts: dict[str, Artifact]


@dataclass(frozen=True)
class _KindRule:
    """One evidence-kind rule: a kind, and the path shapes that select it."""

    kind: str
    directories: tuple[str, ...] = ()
    suffixes: tuple[str, ...] = ()
    substrings: tuple[str, ...] = ()

    def is_match(self, lowered_path: str) -> bool:
        """True when a lower-cased path has any of the shapes in this rule."""
        return (
            any(_is_under(lowered_path, directory) for directory in self.directories)
            or lowered_path.endswith(self.suffixes)
            or any(part in lowered_path for part in self.substrings)
        )


# The first rule that matches decides the kind, so the order is the meaning:
# papers are recognised before the data directory swallows data/papers, and
# traces are recognised before a run log inside results/ is called a result.
EVIDENCE_KIND_RULES: Final[tuple[_KindRule, ...]] = (
    _KindRule("note", directories=("notes",)),
    _KindRule("paper", directories=("references", "data/papers"), suffixes=(".bib",)),
    _KindRule("trace", suffixes=(".tar.gz", ".log"), substrings=("transcript",)),
    _KindRule("code", directories=("scripts", "src"), suffixes=(".py",)),
    _KindRule("dataset", directories=("data",)),
    _KindRule("result", directories=("results",), suffixes=(".json", ".jsonl", ".npz", ".csv")),
)


def _is_under(path: str, directory: str) -> bool:
    """True when the path sits inside the named directory, at any depth."""
    return path.startswith(f"{directory}/") or f"/{directory}/" in path


def evidence_kind(path: str) -> str:
    """Say what kind of thing an evidence path points at.

    The answer is one of note, paper, trace, code, dataset, result, or other,
    decided by the first rule in EVIDENCE_KIND_RULES that the path matches.
    """
    lowered = path.lower()
    for rule in EVIDENCE_KIND_RULES:
        if rule.is_match(lowered):
            return rule.kind
    return "other"


def _node_ir(node: GraphNode) -> dict[str, object]:
    """Describe one node using the short key names the JSON schema uses."""
    return {
        "id": node.node_id,
        "type": node.node_type,
        "text": node.text,
        "status": node.status,
        "evidence": list(node.evidence),
        "log": node.log_date,
        "parent": node.parent,
        "children": list(node.children),
    }


def _mentions_ir(ids: tuple[str, ...], paths: tuple[str, ...]) -> dict[str, object]:
    """Describe the ids and paths some piece of prose refers to."""
    return {"ids": list(ids), "paths": list(paths)}


def to_ir(graph: Graph) -> dict[str, object]:
    """Describe the whole graph as plain data that json.dumps can write.

    Every list is in a fixed order — ids and paths rising, log entries newest
    first — so two reads of an unchanged record produce identical JSON. Entry
    bodies are left out on purpose: the log itself stays the place to read
    the prose, and this description stays small enough to pass around.
    """
    entries = sorted(graph.entries.values(), key=lambda entry: entry.date, reverse=True)
    return {
        "version": IR_VERSION,
        "root": str(graph.root),
        "nodes": [_node_ir(graph.nodes[node_id]) for node_id in sorted(graph.nodes)],
        "entries": [
            {"date": entry.date, "mentions": _mentions_ir(entry.mentions_ids, entry.mentions_paths)}
            for entry in entries
        ],
        "documents": [
            {
                "path": document.path,
                "title": document.title,
                "linked_from": list(document.linked_from),
                "orphan": document.orphan,
                "mentions": _mentions_ir(document.mentions_ids, document.mentions_paths),
            }
            for document in (graph.documents[path] for path in sorted(graph.documents))
        ],
        "artifacts": [
            {
                "path": artifact.path,
                "kind": artifact.kind,
                "exists": artifact.exists,
                "referenced_by": list(artifact.referenced_by),
            }
            for artifact in (graph.artifacts[path] for path in sorted(graph.artifacts))
        ],
    }


# How long a label may be before it is shortened, so no box overflows.
LABEL_LIMIT: Final[int] = 40

# The colour each status gets in the diagram. A status that is not listed
# here — open, planned, running, and anything the validator would reject —
# keeps the diagram's default colour rather than crashing the drawing.
MERMAID_STATUS_CLASS: Final[dict[str, str]] = {
    "supported": "good",
    "survived": "good",
    "done": "good",
    "refuted": "bad",
    "failed": "bad",
    "abandoned": "quiet",
    "unvalidated": "pending",
}

MERMAID_CLASS_DEFS: Final[tuple[str, ...]] = (
    "classDef good fill:#dff5e1,stroke:#2e7d32,color:#14361c;",
    "classDef bad fill:#fbdcdc,stroke:#c62828,color:#4a1010;",
    "classDef quiet fill:#eeeeee,stroke:#9e9e9e,color:#424242;",
    "classDef pending fill:#fff3d6,stroke:#ef6c00,color:#4a2c00;",
)


def _mermaid_id(prefix: str, name: str) -> str:
    """Turn a node id or a file path into a name mermaid accepts for a box."""
    return f"{prefix}_{re.sub(r'[^0-9A-Za-z]+', '_', name)}"


def _safe_excerpt(text: str, limit: int = LABEL_LIMIT) -> str:
    """Shorten text to one short line and escape what would break mermaid."""
    flat = " ".join(text.split())
    if len(flat) > limit:
        flat = flat[: limit - 3].rstrip() + "..."
    return flat.replace('"', "#quot;")


def _mermaid_label(node_id: str, text: str) -> str:
    """Label a box with its full id and a short excerpt of the node's text."""
    excerpt = _safe_excerpt(text)
    return f"{node_id}: {excerpt}" if excerpt else node_id


def _evidence_edges(graph: Graph) -> list[str]:
    """Draw a box for each evidence path and a dashed edge from every citer."""
    lines: list[str] = []
    for path in sorted(graph.artifacts):
        artifact = graph.artifacts[path]
        box = _mermaid_id("e", path)
        lines.append(f'    {box}("{_safe_excerpt(path)}")')
        lines.extend(
            f"    {_mermaid_id('n', node_id)} -.->|{artifact.kind}| {box}"
            for node_id in artifact.referenced_by
        )
    return lines


def _class_lines(graph: Graph) -> list[str]:
    """One colour line per class, naming every box that shares that status."""
    grouped: dict[str, list[str]] = {}
    for node_id in sorted(graph.nodes):
        class_name = MERMAID_STATUS_CLASS.get(graph.nodes[node_id].status)
        if class_name:
            grouped.setdefault(class_name, []).append(_mermaid_id("n", node_id))
    return [f"    class {','.join(boxes)} {name};" for name, boxes in sorted(grouped.items())]


def to_mermaid(graph: Graph, with_evidence: bool = False) -> str:
    """Draw the tree as a mermaid flowchart that renders in any markdown page.

    Each node becomes one box labelled with its id and a short excerpt, and a
    solid edge runs from every parent to its children. Ask for evidence and
    each evidence path becomes a rounded box joined by a dashed edge labelled
    with its kind.
    """
    lines = ["flowchart TD"]
    for node_id in sorted(graph.nodes):
        node = graph.nodes[node_id]
        lines.append(f'    {_mermaid_id("n", node_id)}["{_mermaid_label(node_id, node.text)}"]')
        if node.parent:
            lines.append(f"    {_mermaid_id('n', node.parent)} --> {_mermaid_id('n', node_id)}")
    if with_evidence:
        lines.extend(_evidence_edges(graph))
    lines.extend(f"    {definition}" for definition in MERMAID_CLASS_DEFS)
    lines.extend(_class_lines(graph))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Layer two: the repository — the one place that reads the record from disk.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Index:
    """The lookup tables the builders share while one read is in progress."""

    node_ids: frozenset[str]
    known_paths: tuple[str, ...]
    references: dict[str, tuple[str, ...]]


def _read_text(path: Path) -> str:
    """Read a file as text, treating a file that is not there as empty.

    A missing TREE.md or RESEARCH_LOG.md is a finding for the validator to
    report, not a crash for every reader, so this layer stays quiet about it.
    Undecodable bytes are replaced rather than raised, so one stray character
    in a note cannot stop the whole record from loading.
    """
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _parse_tree(text: str) -> list[grammar.Node]:
    """Parse the node lines of TREE.md using the validator's own parser.

    Lines inside fenced code blocks are examples that document the grammar,
    so they are skipped exactly as the validator skips them. Any line the
    validator's parser rejects is left out of the graph: saying what is wrong
    with it is the validator's job, and this layer only reads what is valid.
    """
    report = grammar.Report()
    nodes: list[grammar.Node] = []
    in_fence = False
    for lineno, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence or not grammar.is_node_line(line.strip()):
            continue
        node = grammar.parse_node(line, lineno, report)
        if node is not None:
            nodes.append(node)
    return nodes


def _references_by_path(parsed: list[grammar.Node]) -> dict[str, tuple[str, ...]]:
    """Map every evidence path to the ids of the nodes that list it."""
    listed: dict[str, list[str]] = {}
    for node in parsed:
        for path in node.evidence:
            listed.setdefault(path, []).append(node.node_id)
    return {path: tuple(sorted(set(ids))) for path, ids in sorted(listed.items())}


def _build_nodes(parsed: list[grammar.Node]) -> dict[str, GraphNode]:
    """Turn parsed lines into nodes wired to their parents and their children.

    A node whose parent is missing from the file keeps no parent rather than
    pointing at nothing, so a half-written tree still loads and can be shown.
    """
    present = {node.node_id for node in parsed}
    children: dict[str, list[str]] = {}
    for node in parsed:
        if node.parent_id in present:
            children.setdefault(node.parent_id, []).append(node.node_id)
    return {
        node.node_id: GraphNode(
            node_id=node.node_id,
            node_type=NODE_TYPE_NAMES.get(node.node_type, node.node_type),
            text=node.text,
            status=node.status,
            evidence=tuple(node.evidence),
            log_date=node.log_date,
            lineno=node.lineno,
            parent=node.parent_id if node.parent_id in present else None,
            children=tuple(sorted(children.get(node.node_id, []))),
        )
        for node in parsed
    }


def _mentions(text: str, index: _Index) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Find the node ids and the known repository paths a piece of text names."""
    found = {match for match in MENTION_ID_RE.findall(text) if match in index.node_ids}
    paths = tuple(path for path in index.known_paths if path in text)
    return tuple(sorted(found)), paths


def _build_entries(text: str, index: _Index) -> dict[str, LogEntry]:
    """Split the log into dated entries and record what each one refers to."""
    entries: dict[str, LogEntry] = {}
    for entry_date, body in grammar.split_log_entries(text).items():
        ids, paths = _mentions(body, index)
        entries[entry_date] = LogEntry(
            date=entry_date, body=body, mentions_ids=ids, mentions_paths=paths
        )
    return entries


def _mentioned_paths(
    nodes: dict[str, GraphNode], entries: dict[str, LogEntry], index: _Index
) -> frozenset[str]:
    """Collect every known path that node text or a log entry body names."""
    found: set[str] = set()
    for entry in entries.values():
        found.update(entry.mentions_paths)
    for node in nodes.values():
        found.update(path for path in index.known_paths if path in node.text)
    return frozenset(found)


def _document_paths(root: Path) -> list[str]:
    """List every markdown file under notes/, as repository-relative paths."""
    return sorted(
        found.relative_to(root).as_posix() for found in root.glob(NOTES_PATTERN) if found.is_file()
    )


def _title_of(text: str, path: str) -> str:
    """Take the document's first heading as its title, or use its filename."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or Path(path).name
    return Path(path).name


def _build_document(root: Path, path: str, index: _Index, mentioned: frozenset[str]) -> Document:
    """Describe one note: its title, who links to it, and what it refers to.

    A note is an orphan when no node lists it as evidence and neither the
    tree nor the log ever names it, which means nobody reading the record
    from the top would ever find it.
    """
    text = _read_text(root / path)
    ids, paths = _mentions(text, index)
    linked_from = index.references.get(path, ())
    return Document(
        path=path,
        title=_title_of(text, path),
        linked_from=linked_from,
        mentions_ids=ids,
        mentions_paths=paths,
        orphan=not linked_from and path not in mentioned,
    )


def _build_artifact(root: Path, path: str, references: dict[str, tuple[str, ...]]) -> Artifact:
    """Describe one evidence path: its kind, whether it is there, and who cites it."""
    return Artifact(
        path=path,
        kind=evidence_kind(path),
        exists=(root / path).exists(),
        referenced_by=references.get(path, ()),
    )


def load(root: Path) -> Graph:
    """Read the research record under `root` and return it as one graph.

    This is the only function in the system that reads the record, and it
    reads it fresh every time it is called: the markdown files are the store,
    and nothing is cached between calls. A missing TREE.md or RESEARCH_LOG.md
    gives an empty part of the graph rather than an error, because reporting
    that is the validator's job.
    """
    root = Path(root)
    if not root.is_dir():
        raise FileNotFoundError(
            f"There is no directory at {root}. Point the root at the project folder "
            "that holds TREE.md and RESEARCH_LOG.md."
        )
    parsed = _parse_tree(_read_text(root / TREE_FILE))
    nodes = _build_nodes(parsed)
    references = _references_by_path(parsed)
    document_paths = _document_paths(root)
    index = _Index(
        node_ids=frozenset(nodes),
        known_paths=tuple(sorted(set(document_paths) | set(references))),
        references=references,
    )
    entries = _build_entries(_read_text(root / LOG_FILE), index)
    mentioned = _mentioned_paths(nodes, entries, index)
    return Graph(
        root=root,
        nodes=nodes,
        entries=entries,
        documents={path: _build_document(root, path, index, mentioned) for path in document_paths},
        artifacts={path: _build_artifact(root, path, references) for path in sorted(references)},
    )
