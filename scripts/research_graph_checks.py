#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Layer 3 (operations): read-only integrity checks over the research graph.

Provenance pinning, drift detection against a pinned evidence hash, orphan
documents, and a combined ``verify`` report all live here. Every function
reads the record through ``research_graph_model`` and returns data or a
findings list; nothing in this module writes to TREE.md, RESEARCH_LOG.md,
or notes/ — that is ``research_graph_write.py``'s job.

Findings are plain sentences, one problem each, prefixed by severity so a
reader (human or agent) can tell at a glance what needs action: ERROR for
something that must be fixed before the record can be trusted, WARNING
for something worth a look but not blocking, INFO for a fact worth
knowing. These three prefixes and the OK/INVALID exit codes come from
``research_graph_model``, the module's one shared home for both
conventions; ``verify`` uses the same ERROR prefix to decide its exit
code, so the prefix on a line is never just decoration.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Final

from research_graph_glossary import glossary_report
from research_graph_model import ERROR, INFO, INVALID, OK, WARNING, Graph, load
from research_graph_review import review_report
from research_graph_verification import load_scorecard_block, verification_report

GRADUATED: Final[frozenset[str]] = frozenset({"survived", "weakened", "failed"})

# Mirrors validate_research.py's SCORECARD_RE (`falsif|scorecard|validat`,
# case-insensitive) so "claim1_falsified.json" still counts, the way the
# validator treats it. Restated, not imported: the architecture routes this
# module through research_graph_model only, never straight to the validator.
# Keep the truncated stems — full words would stop matching real filenames.
_SCORECARD_MARKERS: Final[tuple[str, ...]] = ("falsif", "scorecard", "validat")


def _is_scorecard(path: str) -> bool:
    """True when an evidence path's filename marks it as a scorecard file."""
    name = Path(path).name.lower()
    return any(marker in name for marker in _SCORECARD_MARKERS)


def _git_short_sha(root: Path) -> str:
    """The repository's short commit hash, or "no-git" outside a repo."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except OSError:
        return "no-git"
    sha = result.stdout.strip()
    return sha if result.returncode == 0 and sha else "no-git"


def _load_provenance(full_path: Path) -> dict | None:
    """The "provenance" block of a scorecard file, or None if it has none."""
    return load_scorecard_block(full_path, "provenance")


def _run_validator(root: Path) -> bool:
    """Run the sibling validator as a subprocess; True when it exits 0.

    The child's stdout and stderr are inherited rather than captured, so
    its report streams straight to the console as it runs instead of
    being buffered and replayed later. It is invoked with the current
    interpreter (``sys.executable``) rather than through its own
    "uv run" shebang, so this works even where the ``uv`` command itself
    is not on PATH.
    """
    script = root / "scripts" / "validate_research.py"
    result = subprocess.run([sys.executable, str(script)], cwd=root, check=False)
    return result.returncode == 0


def compute_pin(root: Path, claim_ids: list[str]) -> dict[str, object]:
    """Hash the non-scorecard evidence linked to the given claims.

    Loads the record fresh, collects the union of evidence paths across
    the named claims, and hashes every one that is not itself a
    scorecard file (a scorecard documents the pin; hashing it would be
    circular). Returns a dict ready to embed under a scorecard's
    "provenance" key: the current git commit, today's date, and a
    sha256 hex digest per evidence path. A path that cannot be read
    (missing, unreadable, or a directory) gets the value "missing"
    instead of a digest, and prints a warning naming it. An id in
    ``claim_ids`` that is not a node in the record contributes no
    evidence and prints its own warning.
    """
    graph = load(root)
    paths: set[str] = set()
    for claim_id in claim_ids:
        node = graph.nodes.get(claim_id)
        if node is None:
            print(
                f"{WARNING}{claim_id!r} is not a node in the record, so it "
                "contributes no evidence to this pin — check the id with "
                "the tree or show command.",
                file=sys.stderr,
            )
            continue
        paths.update(path for path in node.evidence if not _is_scorecard(path))
    evidence_sha256: dict[str, str] = {}
    for path in sorted(paths):
        try:
            digest = hashlib.sha256((root / path).read_bytes()).hexdigest()
        except OSError:
            print(
                f"{WARNING}evidence file is missing, so it cannot be hashed for the pin: {path}",
                file=sys.stderr,
            )
            evidence_sha256[path] = "missing"
            continue
        evidence_sha256[path] = digest
    return {
        "git_commit": _git_short_sha(root),
        "pinned_at": date.today().isoformat(),
        "evidence_sha256": evidence_sha256,
    }


def read_pins(root: Path, graph: Graph) -> dict[str, dict]:
    """For each decided claim, the commit, date, and evidence hashes recorded for it.

    For every claim whose status is in GRADUATED, this looks at its
    scorecard evidence files (by filename, via ``_is_scorecard``) in the
    order they are listed on the claim, and takes the first one that
    parses as JSON and carries a top-level "provenance" key. A claim
    with no such file is simply absent from the result — that is how a
    caller tells "not yet pinned" apart from "pinned", without a
    separate boolean.
    """
    pins: dict[str, dict] = {}
    for claim_id, node in graph.nodes.items():
        if node.node_type != "claim" or node.status not in GRADUATED:
            continue
        for path in node.evidence:
            if not _is_scorecard(path):
                continue
            provenance = _load_provenance(root / path)
            if provenance is not None:
                pins[claim_id] = provenance
                break
    return pins


def drift_report(root: Path, graph: Graph) -> list[str]:
    """One finding per evidence file that changed since it was pinned.

    Only claims with a recorded pin (see ``read_pins``) are checked, by
    design: a claim with no pin has nothing to compare against, so it
    stays silent rather than raising a false alarm — precision over
    recall, so legacy records with no pins stay quiet. Every path
    recorded in the pin is re-hashed; a changed hash, a file that has
    gone missing since it was pinned, and a path that was missing when
    pinned but now exists are all reported as drift.
    """
    findings: list[str] = []
    for claim_id, provenance in sorted(read_pins(root, graph).items()):
        evidence_sha256 = provenance.get("evidence_sha256")
        if not isinstance(evidence_sha256, dict):
            continue
        for path, pinned_hash in sorted(evidence_sha256.items()):
            try:
                current_hash = hashlib.sha256((root / path).read_bytes()).hexdigest()
            except OSError:
                current_hash = "missing"
            if current_hash == pinned_hash:
                continue
            if current_hash == "missing":
                reason = "is missing, but it was present when the claim was pinned"
            elif pinned_hash == "missing":
                reason = "now exists, but it was missing when the claim was pinned"
            else:
                reason = "has changed since the claim was pinned"
            findings.append(
                f"{ERROR}{claim_id} evidence file {path} {reason} — re-run the "
                "falsify gate or record in the log why the change is benign."
            )
    return findings


def orphan_report(graph: Graph) -> list[str]:
    """One WARNING finding per notes/ document that nothing points to.

    A document counts as an orphan only when no node's evidence links it
    and no node text or log entry even mentions it in passing (the
    loader already decided this per document; this just reports it).
    """
    return [
        f"{WARNING}{doc.path} is not linked from any node's evidence and is "
        "not mentioned in any node text or log entry — link it as evidence, "
        "mention it in a node or log entry, or delete it if it is stale."
        for doc in sorted(graph.documents.values(), key=lambda d: d.path)
        if doc.orphan
    ]


def _missing_evidence_findings(graph: Graph) -> list[str]:
    """One ERROR finding per artifact whose evidence file is not on disk."""
    return [
        f"{ERROR}evidence file does not exist on disk: {artifact.path} "
        f"(referenced by {', '.join(artifact.referenced_by)}) — restore the "
        "file, or fix the path in the node(s) that reference it."
        for artifact in sorted(graph.artifacts.values(), key=lambda a: a.path)
        if not artifact.exists
    ]


def _unpinned_graduated_claims(graph: Graph, pins: dict[str, dict]) -> int:
    """How many decided claims have no recorded commit, date, and evidence hashes."""
    return sum(
        1
        for node in graph.nodes.values()
        if node.node_type == "claim" and node.status in GRADUATED and node.node_id not in pins
    )


def verify(root: Path) -> int:
    """Run every integrity check and print one combined report.

    In order: the sibling validator as a subprocess (grammar and the
    evidence-exists-on-disk basics), evidence existence per artifact,
    drift, verification scorecards (quote anchors resolve, verdicts match
    statuses, reader runs recorded), clarity reviews (whether an independent
    reader has read each shared document, and whether its complaints quote text
    that is still there), orphan documents, and finally how many decided claims
    still have no recorded evidence hashes. A clarity review never reports on
    the quality of any writing: that judgement belongs to the reader, and this
    only says whether the reading happened and about which text. Each problem
    becomes one "ERROR: " finding,
    and this fails (returns 1) exactly when at least one such finding
    exists — a failed validator run, missing evidence, or drift.
    Orphans are warnings and the unpinned count is informational; on
    their own, neither ever fails the run.
    """
    findings: list[str] = []
    if not _run_validator(root):
        findings.append(
            f"{ERROR}the sibling validator reported TREE.md or RESEARCH_LOG.md "
            "is invalid; see its output above for details."
        )
    graph = load(root)
    pins = read_pins(root, graph)
    findings.extend(_missing_evidence_findings(graph))
    findings.extend(drift_report(root, graph))
    findings.extend(verification_report(root, graph, pins))
    findings.extend(glossary_report(root, graph))
    findings.extend(review_report(root))
    findings.extend(orphan_report(graph))
    unpinned = _unpinned_graduated_claims(graph, pins)
    if unpinned:
        findings.append(
            f"{INFO}{unpinned} claims whose status has been decided carry no "
            f"recorded hash of their evidence files; "
            "run the pin command at the next gate."
        )
    for finding in findings:
        print(finding)
    problems = sum(1 for finding in findings if finding.startswith(ERROR))
    if problems:
        print(f"FAIL — {problems} problem(s)")
        return INVALID
    print(
        "OK — record verified "
        f"({len(graph.nodes)} node(s), {len(graph.artifacts)} artifact(s), "
        f"{len(pins)} pinned claim(s))."
    )
    return OK
