#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Layer 3 (operations): checks over agent-run verification scorecards.

Some claims cannot be verified by arithmetic: their evidence is a model
transcript to be read, a paper to be checked, a label to be discriminated.
An agent is the instrument that verifies them, and this module makes that
verification an artifact instead of a vibe. A scorecard may carry a
top-level "verification" block:

    "verification": {
      "method": "trace-read",
      "protocol": "<what the readers were asked, registered before reading>",
      "inputs": ["results/transcript.jsonl"],
      "verdict": "survives",
      "runs": [
        {"reader": "<model or person>", "at": "2026-08-24",
         "verdict": "survives",
         "quotes": [{"path": "results/transcript.jsonl",
                     "excerpt": "<verbatim span from the file>"}]}
      ]
    }

How many agents verified the claim is derived from the runs list, never
stored as a separate count — a stored number can contradict the list it
summarizes, a derived one cannot. When each verified it is each run's
"at" date, and the report names the latest.

The mechanical half of the bargain, checked here: every quoted excerpt must
appear verbatim in the file it cites (fabricated readings usually die
exactly there), every input must exist on disk, and the scorecard's verdict
must agree with the claim's status in the tree. The judgment half — whether
the verdict is honest — stays with the readers and the norms; a claim with
no verification block is silent, never a false alarm, the same
precision-over-recall policy the recorded evidence hashes follow.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Final

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from research_graph_model import ERROR, INFO, WARNING, Graph  # noqa: E402

# Mirrors the validator's scorecard filename rule (truncated stems, by
# design), restated rather than imported for the same reason the checks
# module restates it: this module depends on the model only.
_SCORECARD_MARKERS: Final[tuple[str, ...]] = ("falsif", "scorecard", "validat")
GRADUATED: Final[frozenset[str]] = frozenset({"survived", "weakened", "failed"})

# The scorecard speaks the falsify skill's vocabulary; the tree speaks the
# status vocabulary. One mapping keeps them honest about each other.
VERDICT_TO_STATUS: Final[dict[str, str]] = {
    "survives": "survived",
    "weakened": "weakened",
    "failed": "failed",
}

# A quote shorter than this (whitespace-collapsed) matches almost anything,
# so it anchors almost nothing.
MIN_ANCHOR_CHARS: Final[int] = 15

ARCHIVE_SUFFIXES: Final[tuple[str, ...]] = (".tar.gz", ".tgz", ".zip", ".gz")


def _collapse(text: str) -> str:
    return " ".join(text.split())


def load_scorecard_block(path: Path, key: str) -> dict[str, object] | None:
    """One named top-level block of a scorecard file, or None if it has none.

    None covers every reason the block cannot be read — missing file, invalid
    JSON, JSON that is not an object, or an object without the key — because
    they all mean the same thing to a caller: this scorecard carries no such
    block to check. Shared by the provenance-pin reader in the checks module
    and the verification reader here, which look up different keys of the
    same file.
    """
    try:
        data = json.loads(path.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    block = data.get(key)
    return block if isinstance(block, dict) else None


def _load_verification(path: Path) -> dict[str, object] | None:
    return load_scorecard_block(path, "verification")


def quote_resolves(root: Path, rel_path: str, excerpt: str) -> bool | None:
    """Whether the excerpt appears verbatim in the cited file.

    Public because the clarity-review module anchors its findings the same
    way. One resolver, so a quote that anchors a claim and a quote that
    anchors a readability finding are held to exactly the same standard.

    None means the file could not be read (reported separately). Both sides
    are whitespace-collapsed, and the excerpt is also tried in its two
    JSON-escaped spellings, so a quote of decoded transcript text still
    resolves against the raw JSONL that stores it escaped.
    """
    try:
        raw = (root / rel_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    haystack = _collapse(raw)
    candidates = (
        excerpt,
        json.dumps(excerpt, ensure_ascii=False)[1:-1],
        json.dumps(excerpt, ensure_ascii=True)[1:-1],
    )
    return any(_collapse(form) in haystack for form in candidates)


def _check_quote(root: Path, claim_id: str, quote: object) -> list[str]:
    """Findings for one quote anchor: shape, length, archive, and resolution."""
    if not isinstance(quote, dict) or not quote.get("path") or not quote.get("excerpt"):
        return [
            f"{WARNING}{claim_id} verification has a malformed quote (needs "
            '"path" and "excerpt") — it anchors nothing until fixed.'
        ]
    rel_path, excerpt = str(quote["path"]), str(quote["excerpt"])
    if rel_path.endswith(ARCHIVE_SUFFIXES):
        return [
            f"{WARNING}{claim_id} verification quotes inside the archive {rel_path}, "
            "which cannot be checked — store traces as plain files so their "
            "quotes stay verifiable."
        ]
    if len(_collapse(excerpt)) < MIN_ANCHOR_CHARS:
        return [
            f"{WARNING}{claim_id} verification quote {_collapse(excerpt)!r} is too "
            f"short to anchor anything (under {MIN_ANCHOR_CHARS} characters) — "
            "quote a longer verbatim span."
        ]
    resolved = quote_resolves(root, rel_path, excerpt)
    if resolved is None:
        return [
            f"{ERROR}{claim_id} verification quotes {rel_path}, which cannot be "
            "read — restore the file or fix the path."
        ]
    if not resolved:
        return [
            f"{ERROR}{claim_id} verification quote does not appear in {rel_path}: "
            f"{_collapse(excerpt)[:80]!r} — a reading that cannot be found in its "
            "source is indistinguishable from a fabricated one; re-read the file "
            "and quote it verbatim."
        ]
    return []


def _check_runs(root: Path, claim_id: str, runs: object) -> tuple[list[str], list[dict]]:
    """Findings for the runs list, plus the well-formed runs for reporting."""
    if not isinstance(runs, list) or not runs:
        return [
            f"{WARNING}{claim_id} has a verification block with no reader runs — "
            "a verification nobody ran is decoration; record at least one run "
            "(reader, date, verdict, quotes)."
        ], []
    findings: list[str] = []
    shaped = [run for run in runs if isinstance(run, dict)]
    if len(shaped) < len(runs):
        findings.append(f"{WARNING}{claim_id} verification has a malformed reader run entry.")
    for run in shaped:
        for quote in run.get("quotes") or []:
            findings.extend(_check_quote(root, claim_id, quote))
    verdicts = sorted({str(run.get("verdict")) for run in shaped if run.get("verdict")})
    if len(verdicts) > 1:
        findings.append(
            f"{WARNING}{claim_id} reader runs disagree ({', '.join(verdicts)}) — "
            "the recorded verdict must say why it overrides the dissent, in the "
            "scorecard or the log."
        )
    return findings, shaped


def _check_block(
    root: Path, claim_id: str, status: str, block: dict[str, object], pinned: frozenset[str]
) -> list[str]:
    """All findings for one claim's verification block."""
    findings: list[str] = []
    for rel_path in block.get("inputs") or []:
        if not (root / str(rel_path)).exists():
            findings.append(
                f"{ERROR}{claim_id} verification input does not exist on disk: "
                f"{rel_path} — restore it or fix the path."
            )
        elif pinned and str(rel_path) not in pinned:
            findings.append(
                f"{WARNING}{claim_id} verification input {rel_path} is not covered "
                "by the claim's recorded evidence hashes, so a later change to it "
                "would go unnoticed — "
                "re-run the pin command with this claim."
            )
    verdict = str(block.get("verdict", ""))
    mapped = VERDICT_TO_STATUS.get(verdict)
    if mapped and mapped != status:
        findings.append(
            f"{ERROR}{claim_id} scorecard verdict {verdict!r} contradicts the "
            f"claim's status [{status}] — one of them is wrong; fix the record "
            "or re-run the gate."
        )
    run_findings, shaped = _check_runs(root, claim_id, block.get("runs"))
    findings.extend(run_findings)
    if shaped:
        dates = sorted(str(run["at"]) for run in shaped if run.get("at"))
        latest = f", latest {dates[-1]}" if dates else ""
        method = str(block.get("method", "unstated method"))
        findings.append(
            f"{INFO}{claim_id} verified by {len(shaped)} reader run(s) ({method}{latest})."
        )
    return findings


def verification_report(root: Path, graph: Graph, pins: dict[str, dict] | None = None) -> list[str]:
    """One finding per problem in the verification block of any decided claim.

    `pins` is the read_pins result when the caller has it (verify does);
    without it the coverage warning stays quiet rather than guessing.
    """
    findings: list[str] = []
    for claim_id, node in sorted(graph.nodes.items()):
        if node.node_type != "claim" or node.status not in GRADUATED:
            continue
        pinned = frozenset()
        if pins and claim_id in pins:
            sha = pins[claim_id].get("evidence_sha256")
            pinned = frozenset(sha) if isinstance(sha, dict) else frozenset()
        for path in node.evidence:
            name = Path(path).name.lower()
            if not any(marker in name for marker in _SCORECARD_MARKERS):
                continue
            block = _load_verification(root / path)
            if block is not None:
                findings.extend(_check_block(root, claim_id, node.status, block, pinned))
    return findings
