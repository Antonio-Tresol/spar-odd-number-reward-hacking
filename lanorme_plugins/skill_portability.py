"""HSKILL-001/002/003: harness-specific SKILL.md checks.

Complements lanorme's built-in `skills` check (SKILL-001..006), which owns spec
compliance. These are the harness's own concerns and do not overlap:

    HSKILL-001  no machine-specific absolute path in a skill body. Skills are
                shared between machines and teammates; a `/Users/...` path
                breaks on clone.
    HSKILL-002  no unrecognized frontmatter key (typo catcher).  [warning]
    HSKILL-003  `.agents/skills` (where Codex looks) resolves to the same files
                as `.claude/skills` (where Claude Code looks). Catches the
                Windows case where git checks a symlink out as a text file, and
                the case where the two directories have drifted apart.

A rule checking that descriptions state WHEN to use a skill was removed: across
four real skill collections it produced 43 findings and no true positives.
"Convert a Jupyter notebook to a marimo notebook" says when to use it perfectly
well without containing the phrase "use when". Whether a description triggers
reliably is a judgement a regex cannot make.

Frontmatter is read with a minimal top-level key scanner rather than a YAML
parser, so the check stays dependency-free inside lanorme's environment. Any
frontmatter that will not parse at all is lanorme's SKILL-006, not ours.

Run:
    lanorme check . --check=skill_portability
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from lanorme import CheckResult, Status, Violation, register

from ._common import scan_tree

# A user directory, not any path: /home/app in a Dockerfile is the same on every
# machine. C:\ needed a single escape, not two, so Windows paths never matched.
ABS_PATH_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:/Users/|/home/)[A-Za-z0-9._-]+/|C:\\Users\\|~/(?:Documents|Desktop|Downloads)"
)
INLINE_CODE_RE: Final[re.Pattern[str]] = re.compile(r"`[^`]*`")
URL_RE: Final[re.Pattern[str]] = re.compile(r"https?://\S+")
FRONTMATTER_RE: Final[re.Pattern[str]] = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
TOP_LEVEL_KEY_RE: Final[re.Pattern[str]] = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):")

# Keep in sync with https://code.claude.com/docs/en/skills (frontmatter table).
# An earlier, shorter list reported documented fields such as `model` and
# `argument-hint` as typos, including on Anthropic's own published skills.
KNOWN_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "name",
        "description",
        "when_to_use",
        "effort",
        "user_invocable",
        "user-invocable",
        "disable-model-invocation",
        "allowed-tools",
        "disallowed-tools",
        "metadata",
        "compatibility",
        "license",
        "version",
        "model",
        "argument-hint",
        "arguments",
        "context",
        "agent",
        "hooks",
        "paths",
        "shell",
    }
)
HSKILL_001: Final[str] = "HSKILL-001: skills contain no machine-specific absolute paths"
HSKILL_002: Final[str] = "HSKILL-002: frontmatter keys are recognized (warning)"
HSKILL_003: Final[str] = "HSKILL-003: .agents/skills and .claude/skills serve the same files"

CLAUDE_SKILLS: Final[str] = ".claude/skills"
CODEX_SKILLS: Final[str] = ".agents/skills"


@dataclass(frozen=True)
class Frontmatter:
    """Top-level keys and the raw text of a skill's frontmatter."""

    keys: tuple[str, ...]
    text: str

    @property
    def is_manual_only(self) -> bool:
        return "disable-model-invocation: true" in self.text.lower()

    def value_of(self, key: str) -> str:
        """Text following `key:` up to the next top-level key. '' when absent."""
        pattern = re.compile(
            rf"^{re.escape(key)}:(.*?)(?=^[A-Za-z][A-Za-z0-9_-]*:|\Z)", re.DOTALL | re.MULTILINE
        )
        match = pattern.search(self.text)
        return match.group(1).strip() if match else ""


def parse_frontmatter(text: str) -> Frontmatter | None:
    match = FRONTMATTER_RE.match(text)
    if match is None:
        return None
    body = match.group(1)
    keys = tuple(
        m.group(1) for m in (TOP_LEVEL_KEY_RE.match(line) for line in body.splitlines()) if m
    )
    return Frontmatter(keys=keys, text=body)


def check_portability(text: str, file: str) -> list[Violation]:
    """Machine-specific paths in skill prose.

    Scans the whole file so reported line numbers are real, and skips fenced
    blocks, inline code and URLs: a skill that documents a bad path as an
    example, or quotes a traceback, is teaching rather than depending on it.
    """
    found: list[Violation] = []
    in_fence = False
    for lineno, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        cleaned = INLINE_CODE_RE.sub(" ", line)
        cleaned = URL_RE.sub(" ", cleaned)
        match = ABS_PATH_RE.search(cleaned)
        if match is None:
            continue
        found.append(
            Violation(
                file=file,
                line=lineno,
                rule=HSKILL_001,
                message=f"Machine-specific absolute path near '{match.group(0)}'",
                fix="Move the path to a gitignored CLAUDE.local.md and reference it generically",
            )
        )
    return found


def check_field_names(frontmatter: Frontmatter, file: str) -> list[Violation]:
    return [
        Violation(
            file=file,
            line=1,
            rule=HSKILL_002,
            message=f"Unrecognized frontmatter key '{key}'",
            fix=f"Remove it or correct the spelling; known keys: {', '.join(sorted(KNOWN_FIELDS))}",
        )
        for key in frontmatter.keys
        if key not in KNOWN_FIELDS
    ]


def check_codex_link(root: Path) -> tuple[list[Violation], list[Violation]]:
    """Codex reads .agents/skills; Claude Code reads .claude/skills.

    A symlink normally makes one directory serve both. It fails in two ways worth
    catching loudly, because both fail silently otherwise: git on Windows without
    `core.symlinks` writes the link out as a text file, and a copied directory
    drifts once someone edits one side.
    """
    claude_dir = root / CLAUDE_SKILLS
    codex_dir = root / CODEX_SKILLS
    if not claude_dir.is_dir():
        return [], []

    def finding(rule: str, message: str, fix: str) -> Violation:
        return Violation(file=CODEX_SKILLS, line=1, rule=rule, message=message, fix=fix)

    if not codex_dir.exists():
        return [], [
            finding(
                HSKILL_003,
                "No .agents/skills, so Codex will not find this project's skills",
                f"Run: mkdir -p .agents && ln -s ../{CLAUDE_SKILLS} {CODEX_SKILLS}",
            )
        ]
    if codex_dir.is_file():
        return [
            finding(
                HSKILL_003,
                ".agents/skills is a file, not a directory. A symlink was checked out "
                "as text, so Codex silently loads no skills (usual cause: git on Windows "
                "without core.symlinks)",
                "Enable symlinks (`git config core.symlinks true`, Developer Mode on "
                "Windows) and re-checkout, or replace it with a copy of .claude/skills",
            )
        ], []
    if codex_dir.is_symlink():
        return [], []  # resolves to the same files by construction

    claude_names = {p.name for p in claude_dir.iterdir() if p.is_dir()}
    codex_names = {p.name for p in codex_dir.iterdir() if p.is_dir()}
    # Only skills MISSING on the Codex side matter. Extra Codex-only skills are a
    # deliberate layout, not drift.
    if claude_names - codex_names:
        missing = ", ".join(sorted(claude_names - codex_names))
        return [
            finding(
                HSKILL_003,
                f".agents/skills is a copy that has drifted from .claude/skills ({missing})",
                "Re-copy, or replace the copy with a symlink so one set of files serves both",
            )
        ], []
    return [], []


@dataclass
class SkillPortabilityCheck:
    """Harness-specific SKILL.md checks that complement lanorme's spec rules."""

    name: str = "skill_portability"
    description: str = "Harness SKILL.md checks: portability, trigger phrasing, frontmatter typos"
    enabled: bool = True
    check_codex_skills: bool = True
    rules: list[str] = field(
        default_factory=lambda: [
            "HSKILL-001: skills contain no machine-specific absolute paths",
            "HSKILL-002: frontmatter keys are recognized (warning)",
            "HSKILL-003: .agents/skills and .claude/skills serve the same files",
        ]
    )

    def configure(self, *, settings: dict[str, object]) -> None:
        enabled = settings.get("enabled")
        if isinstance(enabled, bool):
            self.enabled = enabled
        codex = settings.get("check_codex_skills")
        if isinstance(codex, bool):
            self.check_codex_skills = codex

    def _scan_file(self, path: Path, file: str) -> tuple[list[Violation], list[Violation]]:
        text = path.read_text(encoding="utf-8")
        violations = check_portability(text, file)
        frontmatter = parse_frontmatter(text)
        if frontmatter is None:
            return violations, []  # unparseable frontmatter is lanorme's SKILL-006
        warnings = check_field_names(frontmatter, file)
        return violations, warnings

    def run(self, *, src_root: str) -> CheckResult:
        if not self.enabled:
            return CheckResult(check=self.name, status=Status.PASS)
        result = scan_tree(
            name=self.name, src_root=src_root, pattern="SKILL.md", scan=self._scan_file
        )
        link_violations, link_warnings = (
            check_codex_link(Path(src_root)) if self.check_codex_skills else ([], [])
        )
        result.violations.extend(link_violations)
        result.warnings.extend(link_warnings)
        if result.violations:
            result.status = Status.FAIL
        elif result.warnings:
            result.status = Status.WARN
        return result


register(SkillPortabilityCheck())
