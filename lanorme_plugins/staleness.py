"""STALE-001/002: the bookkeeping artefacts have kept up with the work.

Every other check verifies internal consistency: that a claim's evidence exists,
that statuses are legal, that numbers resolve. None of them notice when the
research tree simply stopped being updated. A project can run twenty experiments
against a placeholder `Q1` and pass everything.

    STALE-001  no bookkeeping artefact has changed while N commits ADDED or
               MODIFIED files under `results/`.  [warning]
    STALE-002  a document declares `updated:` in its frontmatter, and git shows
               the file changed after that date.  [warning]

Both use git, so both are silent outside a repository or before the first
commit. Both are warnings: only a person can say whether an experiment produced
a belief worth recording, and a gate that blocks on that judgement gets bypassed.

Configure:

    [staleness]
    watch = ["results"]                       # only results imply a finding
    artefacts = ["TREE.md", "RESEARCH_LOG.md"]  # either one clears the count
    max_commits_behind = 8
    dated_docs = ["reports/**/*.md"]          # enables STALE-002

Deliberately narrow. Counting every commit that touched `scripts/` treated
tooling syncs and refactors as evidence that experiments had run, and anchoring
only on TREE.md made the advice "note it in the log" impossible to satisfy.

Run:
    lanorme check . --check=staleness
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Final

from lanorme import CheckResult, Status, Violation, register

from ._common import is_glob_match

UPDATED_RE: Final[re.Pattern[str]] = re.compile(
    r"^updated:\s*(\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE
)
FRONTMATTER_RE: Final[re.Pattern[str]] = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)

STALE_001: Final[str] = "STALE-001: bookkeeping artefacts keep pace with the work"
STALE_002: Final[str] = "STALE-002: a document's `updated:` date matches its last change"


def git(root: Path, *args: str) -> str | None:
    """Run git, returning stripped stdout, or None when git cannot answer."""
    try:
        done = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def is_git_repo(root: Path) -> bool:
    return git(root, "rev-parse", "--git-dir") is not None


def last_commit_for(root: Path, path: str) -> str | None:
    """Short hash of the last commit touching `path`."""
    out = git(root, "log", "-1", "--format=%h", "--", path)
    return out or None


def commits_adding_results_since(root: Path, since: str, patterns: list[str]) -> int:
    """Commits since `since` that ADDED or MODIFIED a watched file.

    Deliberately not a plain path count. Deletions, renames and pure refactors
    move files without producing findings, and vendored tooling syncs touch
    `scripts/` without any experiment having run. Counting those told projects
    their bookkeeping had fallen behind when no work had happened.
    """
    out = git(
        root,
        "log",
        "--format=%H",
        "--diff-filter=AM",
        f"{since}..HEAD",
        "--",
        *patterns,
    )
    return len(out.splitlines()) if out else 0


def latest_artefact_commit(root: Path, artefacts: list[str]) -> str | None:
    """The most recent commit touching ANY bookkeeping artefact.

    Anchoring on TREE.md alone made the advice "note in the log why nothing
    changed" impossible to satisfy: a log-only commit moved nothing.
    """
    out = git(root, "log", "-1", "--format=%h", "--", *artefacts)
    return out or None


def last_commit_date(root: Path, path: str) -> date | None:
    # %as (author date) survives rebase, amend and cherry-pick; %cs does not.
    out = git(root, "log", "-1", "--follow", "--format=%as", "--", path)
    try:
        return date.fromisoformat(out) if out else None
    except ValueError:
        return None


def declared_updated(text: str) -> date | None:
    """The `updated:` date in a document's frontmatter, if present."""
    front = FRONTMATTER_RE.match(text)
    if front is None:
        return None
    found = UPDATED_RE.search(front.group(1))
    if found is None:
        return None
    try:
        return date.fromisoformat(found.group(1))
    except ValueError:
        return None


@dataclass
class StalenessCheck:
    """Bookkeeping artefacts have kept up with the work."""

    name: str = "staleness"
    description: str = "Research bookkeeping keeps pace with the code and results"
    enabled: bool = True
    max_commits_behind: int = 8
    watch: list[str] = field(default_factory=lambda: ["results"])
    artefacts: list[str] = field(default_factory=lambda: ["TREE.md", "RESEARCH_LOG.md"])
    dated_docs: list[str] = field(default_factory=list)
    rules: list[str] = field(
        default_factory=lambda: [
            "STALE-001: bookkeeping artefacts keep pace with the work (warning)",
            "STALE-002: a document's `updated:` date matches its last change (warning)",
        ]
    )

    def configure(self, *, settings: dict[str, object]) -> None:
        enabled = settings.get("enabled")
        if isinstance(enabled, bool):
            self.enabled = enabled
        behind = settings.get("max_commits_behind")
        if isinstance(behind, int):
            self.max_commits_behind = behind
        for key in ("watch", "artefacts", "dated_docs"):
            value = settings.get(key)
            if isinstance(value, list):
                setattr(self, key, [str(v) for v in value])

    def check_artefacts(self, root: Path) -> list[Violation]:
        found: list[Violation] = []
        present = [a for a in self.artefacts if (root / a).is_file()]
        for artefact in present[:1]:  # one anchor, one warning
            anchor = latest_artefact_commit(root, self.artefacts)
            if anchor is None:
                continue  # never committed; nothing to measure against
            behind = commits_adding_results_since(root, anchor, self.watch)
            if behind <= self.max_commits_behind:
                continue
            found.append(
                Violation(
                    file=artefact,
                    line=1,
                    rule=STALE_001,
                    message=(
                        f"No bookkeeping artefact has changed while {behind} commits "
                        f"added or modified files under {', '.join(self.watch)}"
                    ),
                    fix=(
                        "Record what those runs established: move an experiment to [done], "
                        "add the claims it produced, or note in the log why nothing changed"
                    ),
                )
            )
        return found

    def check_dated_docs(self, root: Path) -> list[Violation]:
        found: list[Violation] = []
        for path in sorted(root.rglob("*.md")):
            if ".git" in path.parts:
                continue
            relative = path.relative_to(root).as_posix()
            if not is_glob_match(relative, self.dated_docs):
                continue
            declared = declared_updated(path.read_text(encoding="utf-8"))
            if declared is None:
                continue
            changed = last_commit_date(root, relative)
            if changed is None or changed <= declared:
                continue
            found.append(
                Violation(
                    file=relative,
                    line=1,
                    rule=STALE_002,
                    message=f"Frontmatter says updated: {declared}, but the file changed on {changed}",
                    fix=f"Set `updated: {changed}` and confirm the content still reflects the data",
                )
            )
        return found

    def run(self, *, src_root: str) -> CheckResult:
        root = Path(src_root)
        if not self.enabled or not is_git_repo(root):
            return CheckResult(check=self.name, status=Status.PASS)
        warnings = self.check_artefacts(root) + self.check_dated_docs(root)
        status = Status.WARN if warnings else Status.PASS
        return CheckResult(check=self.name, status=status, warnings=warnings)


register(StalenessCheck())
