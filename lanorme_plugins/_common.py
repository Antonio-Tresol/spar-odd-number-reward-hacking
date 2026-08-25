"""Shared plumbing for the harness's lanorme checks."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Final

from lanorme import CheckResult, Status, Violation

SKIP_PARTS: Final[frozenset[str]] = frozenset(
    {
        ".git",
        ".venv",
        "__pycache__",
        "node_modules",
    }
)

# (violations, warnings) produced by scanning one file.
FileScan = Callable[[Path, str], "tuple[list[Violation], list[Violation]]"]


def scan_tree(*, name: str, src_root: str, pattern: str, scan: FileScan) -> CheckResult:
    """Run `scan` over every file matching `pattern` and aggregate the result.

    Status is FAIL when anything is a violation, WARN when only warnings, else PASS.
    """
    root = Path(src_root)
    violations: list[Violation] = []
    warnings: list[Violation] = []
    for path in sorted(root.rglob(pattern)):
        if any(part in SKIP_PARTS for part in path.parts):
            continue
        found, warned = scan(path, str(path.relative_to(root)))
        violations.extend(found)
        warnings.extend(warned)
    status = Status.FAIL if violations else (Status.WARN if warnings else Status.PASS)
    return CheckResult(check=name, status=status, violations=violations, warnings=warnings)


def normalize(text: str) -> str:
    """Collapse all whitespace to single spaces.

    Required before substring-matching a YAML value: folded block scalars (`>-`)
    wrap lines mid-phrase, so a literal like "use when" can be split across a
    newline and silently fail to match.
    """
    return " ".join(text.split())


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Compile a glob to a regex with sane `**` semantics.

    `fnmatch` is not enough: it treats `**/` as requiring a separator, so
    `reports/**/*.md` fails to match `reports/findings.md`. Here `**/` matches
    zero or more directories, `**` crosses separators, and `*` and `?` stay
    within one segment.
    """
    out: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")  # zero or more directories
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")  # crosses separators
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")  # within one segment
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile(f"^{''.join(out)}$")


def is_glob_match(path: str, patterns: "list[str]") -> bool:
    """True when `path` matches any pattern."""
    return any(glob_to_regex(pattern).match(path) for pattern in patterns)
