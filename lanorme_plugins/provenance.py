"""PROV-001/002/003: every number in a deliverable traces to a results file.

`validate-claims` is a protocol an agent follows; this is the part a machine can
check. A claim in prose carries an HTML comment naming the value and where it
came from, and the check resolves it against the file on disk:

    The detector fired on 37% of cued prompts.
    <!-- claim: 0.37 from results/pilot.json#detector.false_alarm_rate -->

    Agreement was kappa = 0.43.
    <!-- claim: 0.43 from results/pilot.json#agreement.kappa tol=0.01 -->

The comment is invisible in rendered Markdown, so a document stays readable while
every number in it stays anchored.

    PROV-001  the claim's source file or key path does not resolve
    PROV-002  the value on disk does not match the value claimed
    PROV-003  a claim-bearing file reports statistics but carries no claim
              marker at all (opt-in; off unless `claim_bearing` is configured)

PROV-003 deliberately reports once per FILE, not once per number. Deciding
line-by-line whether a figure is a reported result or a hyperparameter, a
convention, a quotation or a threshold is a judgement a regex cannot make: an
earlier per-line version flagged "learning rate to 0.001", "the top 5% of
prompts" and "p < 0.05" in a methods section. Once a document adopts the
convention at all, the author is trusted with the rest.

Matching is rounding-aware: a claim of `0.37` accepts a stored `0.3712`, because
it agrees to the precision actually written down. An explicit `tol=` overrides.

Configure:

    [provenance]
    claim_bearing = ["reports/**/*.md", "findings/**/*.md"]   # enables PROV-003

Run:
    lanorme check . --check=provenance
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from lanorme import CheckResult, Status, Violation, register

from ._common import is_glob_match, scan_tree

# <!-- claim: 0.37 from results/pilot.json#detector.false_alarm_rate tol=0.01 -->
CLAIM_RE: Final[re.Pattern[str]] = re.compile(
    r"<!--\s*claim:\s*(?P<value>-?[\d.]+(?:[eE][-+]?\d+)?)\s+from\s+(?P<path>[^\s#]+)"
    r"(?:#(?P<key>[^\s]+))?(?:\s+tol=(?P<tol>[-+\d.eE]+))?\s*-->"
)
# Numbers that look like reported statistics rather than incidental counts.
STAT_RE: Final[re.Pattern[str]] = re.compile(
    r"(?<![\w.])(?:\d{1,3}\.\d+%|\d{1,3}%|p\s*[=<]\s*0?\.\d+|0\.\d{2,})(?![\w])"
)
DOC_SUFFIXES: Final[frozenset[str]] = frozenset({".md"})

PROV_001: Final[str] = "PROV-001: claim source resolves to a file and key on disk"
PROV_002: Final[str] = "PROV-002: claimed value matches the value on disk"
PROV_003: Final[str] = "PROV-003: a claim-bearing file anchors its figures"


@dataclass(frozen=True)
class Claim:
    """One `<!-- claim: ... -->` marker."""

    line: int
    value: float
    path: str
    key: str | None
    tol: float | None
    literal: str = ""

    @property
    def decimals(self) -> int:
        """Digits after the point in the value AS WRITTEN.

        Derived from the source text, never from the parsed float: repr of
        1.23e-05 splits to "23e-05" and would report six places for a number
        the author wrote to seven.
        """
        mantissa = self.literal.split("e")[0].split("E")[0]
        places = len(mantissa.split(".", 1)[1]) if "." in mantissa else 0
        exponent = re.search(r"[eE]([-+]?\d+)", self.literal)
        return places - int(exponent.group(1)) if exponent else places


FENCE_RE: Final[re.Pattern[str]] = re.compile(r"^\s*(?:```|~~~)")
INLINE_CODE_RE: Final[re.Pattern[str]] = re.compile(r"`[^`]*`")
# A number introduced by `=` or `:` is a setting, not a reported result.
CONFIG_SHAPE_RE: Final[re.Pattern[str]] = re.compile(r"[=:]\s*-?[\d.]")
URL_RE: Final[re.Pattern[str]] = re.compile(r"https?://\S+|\]\([^)]*\)")
FOOTNOTE_RE: Final[re.Pattern[str]] = re.compile(r"^\s*\[\^")


def iter_prose_lines(text: str) -> "list[tuple[int, str]]":
    """Numbered lines outside fenced code blocks and YAML frontmatter.

    Markers inside a fence are documentation showing the syntax, not claims
    about this project's results, so validating them would flag every example.
    Both ``` and ~~~ fences count.
    """
    lines: list[tuple[int, str]] = []
    raw = text.splitlines()
    in_fence = False
    start = 0
    # Skip YAML frontmatter: `threshold: 0.75` there is configuration.
    if raw and raw[0].strip() == "---":
        for index in range(1, len(raw)):
            if raw[index].strip() == "---":
                start = index + 1
                break
    for offset, line in enumerate(raw[start:]):
        lineno = start + offset + 1
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            lines.append((lineno, line))
    return lines


def is_prose_statistic(line: str) -> bool:
    """True when a line reports a figure, rather than merely containing digits.

    Every exclusion here corresponds to a false positive found by adversarial
    testing: hyperparameters (`learning rate to 0.001`), conventions written as
    settings, digits inside URLs, quoted figures from other papers, table rows,
    footnote definitions, and numbers inside inline code spans.
    """
    stripped = line.strip()
    if not stripped or stripped.startswith(">") or FOOTNOTE_RE.match(stripped):
        return False
    if stripped.count("|") >= 2:  # a table row, with or without a leading pipe
        return False
    cleaned = INLINE_CODE_RE.sub(" ", line)
    cleaned = URL_RE.sub(" ", cleaned)
    if CONFIG_SHAPE_RE.search(cleaned):  # `alpha = 0.05`, `threshold: 0.75`
        return False
    return bool(STAT_RE.search(cleaned))


def parse_claims(text: str) -> list[Claim]:
    claims: list[Claim] = []
    for lineno, line in iter_prose_lines(text):
        for match in CLAIM_RE.finditer(line):
            try:
                value = float(match["value"])
            except ValueError:
                continue
            tol = float(match["tol"]) if match["tol"] else None
            claims.append(Claim(lineno, value, match["path"], match["key"], tol, match["value"]))
    return claims


def resolve_key(data: object, key: str) -> object | None:
    """Walk a dotted key path, supporting list indices: `runs.0.accuracy`."""
    current = data
    for part in key.split("."):
        if isinstance(current, dict):
            if part not in current:
                return None
            current = current[part]
        elif isinstance(current, list):
            if not part.lstrip("-").isdigit():
                return None
            index = int(part)
            if not -len(current) <= index < len(current):
                return None
            current = current[index]
        else:
            return None
    return current


def as_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    return float(value) if isinstance(value, (int, float)) else None


def is_match(claimed: float, actual: float, claim: Claim) -> bool:
    """Rounding-aware comparison, honouring an explicit tolerance."""
    if claim.tol is not None:
        return abs(claimed - actual) <= claim.tol
    if math.isclose(claimed, actual, rel_tol=1e-9, abs_tol=1e-12):
        return True
    return round(actual, claim.decimals) == claimed


def check_claim(claim: Claim, root: Path, file: str) -> Violation | None:
    source = root / claim.path
    if not source.is_file():
        return Violation(
            file=file,
            line=claim.line,
            rule=PROV_001,
            message=f"Claim cites `{claim.path}`, which does not exist",
            fix="Point the claim at a results file that exists, or re-run the experiment",
        )
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return Violation(
            file=file,
            line=claim.line,
            rule=PROV_001,
            message=f"Claim cites `{claim.path}`, which is not readable JSON",
            fix="Cite a JSON results file, or add a key path the checker can resolve",
        )
    if claim.key is None:
        return Violation(
            file=file,
            line=claim.line,
            rule=PROV_001,
            message=f"Claim cites `{claim.path}` with no key path",
            fix="Add the key, e.g. `#detector.false_alarm_rate`",
        )
    found = resolve_key(data, claim.key)
    if found is None:
        return Violation(
            file=file,
            line=claim.line,
            rule=PROV_001,
            message=f"Key `{claim.key}` not found in `{claim.path}`",
            fix="Correct the key path; dotted paths and list indices are supported",
        )
    actual = as_number(found)
    if actual is None:
        return Violation(
            file=file,
            line=claim.line,
            rule=PROV_001,
            message=f"Key `{claim.key}` in `{claim.path}` is not a number",
            fix="Cite a numeric field",
        )
    if not is_match(claim.value, actual, claim):
        return Violation(
            file=file,
            line=claim.line,
            rule=PROV_002,
            message=f"Claim says {claim.value}, but `{claim.path}#{claim.key}` holds {actual}",
            fix="Update the prose and the claim marker to the current value, or re-run the experiment",
        )
    return None


def first_unanchored_statistic(text: str) -> int | None:
    """Line of the first reported statistic, when the file has NO marker at all.

    Returns None as soon as any claim marker is present: a document that has
    adopted the convention is trusted with the rest, because distinguishing a
    result from a hyperparameter line by line is not something a regex can do.
    """
    prose = iter_prose_lines(text)
    if any(CLAIM_RE.search(line) for _, line in prose):
        return None
    for lineno, line in prose:
        if not line.startswith("    ") and is_prose_statistic(line):
            return lineno
    return None


@dataclass
class ProvenanceCheck:
    """Numbers in deliverables trace to results files."""

    name: str = "provenance"
    description: str = "Claim provenance: numbers in documents trace to results files"
    enabled: bool = True
    claim_bearing: list[str] = field(default_factory=list)
    rules: list[str] = field(
        default_factory=lambda: [
            "PROV-001: claim source resolves to a file and key on disk",
            "PROV-002: claimed value matches the value on disk",
            "PROV-003: a claim-bearing file anchors its figures (warning)",
        ]
    )

    def configure(self, *, settings: dict[str, object]) -> None:
        enabled = settings.get("enabled")
        if isinstance(enabled, bool):
            self.enabled = enabled
        globs = settings.get("claim_bearing")
        if isinstance(globs, list):
            self.claim_bearing = [str(g) for g in globs]

    def is_claim_bearing(self, file: str) -> bool:
        return is_glob_match(file, self.claim_bearing)

    def _scan_file(self, path: Path, file: str) -> tuple[list[Violation], list[Violation]]:
        if path.suffix not in DOC_SUFFIXES:
            return [], []
        text = path.read_text(encoding="utf-8")
        # scan_tree passes file = path.relative_to(root), so walk back up to root.
        root = path.parents[len(Path(file).parts) - 1]
        violations = [
            found
            for found in (check_claim(claim, root, file) for claim in parse_claims(text))
            if found is not None
        ]
        warnings: list[Violation] = []
        if self.is_claim_bearing(file):
            lineno = first_unanchored_statistic(text)
            if lineno is not None:
                warnings.append(
                    Violation(
                        file=file,
                        line=lineno,
                        rule=PROV_003,
                        message="This file reports figures but carries no claim markers",
                        fix=(
                            "Anchor its numbers to their source, e.g. "
                            "`<!-- claim: 0.37 from results/pilot.json#rate -->`"
                        ),
                    )
                )
        return violations, warnings

    def run(self, *, src_root: str) -> CheckResult:
        if not self.enabled:
            return CheckResult(check=self.name, status=Status.PASS)
        return scan_tree(name=self.name, src_root=src_root, pattern="*.md", scan=self._scan_file)


register(ProvenanceCheck())
