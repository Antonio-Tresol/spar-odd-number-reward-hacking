"""NB-000/001: report notebooks pass the same gates as promoted code.

Notebook code cells escape every ``*.py``-scanning check, so the moment a
notebook is promoted to a deliverable its code is the least-linted code in the
project. This check closes the gap: it extracts the code cells of each
``.ipynb``, concatenates them into one synthetic module per notebook (imports
in early cells must stay visible to import-gated rules like TENSOR-001), runs
the configured file-scoped checks against that module, and maps every finding
back to the notebook.

    NB-000  a code cell (or a whole notebook file) could not be parsed and was
            skipped.  [warning]
    NB-001  umbrella rule: findings are re-reported under their ORIGINAL codes
            (TYPE-002, SHELL-001, TENSOR-001, ...), so `select`/`ignore` apply
            to notebooks exactly as they do to plain Python.

Findings carry the notebook path, the line WITHIN the cell, and a
``code cell N`` tag in the message (N counts code cells only, 1-based).
Inline ``# noqa`` inside a cell is not seen by the CLI's inline-ignore pass
(it reads raw file lines, and a notebook is JSON) — silence notebook findings
via ``ignore`` / ``per-file-ignores`` instead.

Explore-mode notebooks stay exempt two ways, mirroring how ruff is configured:

* ``exclude`` globs on this check (default ``**/archive/**``), on top of the
  project-wide lanorme ``exclude``;
* ruff's own ``exclude`` / ``extend-exclude`` (from ruff.toml, .ruff.toml, or
  pyproject.toml), so the set of notebooks ruff formats is exactly the set
  lanorme gates.

Configure:

    [notebooks]
    checks = ["strong_types", "file_limits", "security_calls", "tensors"]
    exclude = ["**/archive/**"]       # explore-mode notebooks, never gated
    respect_ruff_excludes = true      # honour ruff's exclude/extend-exclude

Run:
    lanorme check . --check=notebooks
"""

from __future__ import annotations

import ast
import fnmatch
import importlib
import json
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from lanorme import Check, CheckResult, Status, Violation, get_check, register
from lanorme.discovery import iter_files

from ._common import is_glob_match

DEFAULT_CHECKS: Final[tuple[str, ...]] = (
    "strong_types",
    "file_limits",
    "security_calls",
    "tensors",
)
NB_000: Final[str] = "NB-000: notebook cell could not be parsed"
MAGIC_PREFIX: Final[str] = "# nb-magic:"
RUFF_CONFIG_FILES: Final[tuple[str, ...]] = ("ruff.toml", ".ruff.toml", "pyproject.toml")


@dataclass(frozen=True)
class _CellSpan:
    """Where one code cell landed in the synthetic module (1-based, inclusive)."""

    start: int
    end: int
    ordinal: int


@dataclass(frozen=True)
class _Extraction:
    """One notebook flattened to a synthetic module plus its cell map."""

    source: str
    spans: tuple[_CellSpan, ...]
    warnings: tuple[Violation, ...]


def _ruff_table(*, root: Path) -> dict[str, object]:
    """The active ruff configuration table under *root*, or empty.

    Mirrors ruff's own discovery order: ruff.toml and .ruff.toml hold the table
    at top level, pyproject.toml holds it under ``[tool.ruff]``.
    """
    for name in RUFF_CONFIG_FILES:
        path = root / name
        if not path.is_file():
            continue
        try:
            parsed = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            continue
        if name == "pyproject.toml":
            tool = parsed.get("tool")
            ruff = tool.get("ruff") if isinstance(tool, dict) else None
            if isinstance(ruff, dict):
                return ruff
            continue
        return parsed
    return {}


def _ruff_excludes(*, root: Path) -> list[str]:
    """ruff's ``exclude`` + ``extend-exclude`` globs, verbatim."""
    table = _ruff_table(root=root)
    patterns: list[str] = []
    for key in ("exclude", "extend-exclude"):
        value = table.get(key)
        if isinstance(value, list):
            patterns.extend(str(item) for item in value)
    return patterns


def _ruff_excluded(*, relative: str, patterns: list[str]) -> bool:
    """True when *relative* matches a ruff exclude pattern.

    Ruff semantics differ from plain fnmatch in two ways this must honour: a
    pattern without a slash matches the basename of the file or any parent
    directory (so ``*.ipynb`` and ``archive`` work), and a pattern naming a
    directory excludes everything beneath it (so ``notebooks/archive`` works).
    """
    for pattern in patterns:
        if "/" not in pattern:
            if any(fnmatch.fnmatch(part, pattern) for part in relative.split("/")):
                return True
        elif (
            relative == pattern
            or relative.startswith(f"{pattern}/")
            or is_glob_match(relative, [pattern, f"{pattern}/**"])
        ):
            return True
    return False


def _cell_lines(*, source: object) -> list[str]:
    """A cell's source as a list of lines; nbformat stores str or list of str."""
    if isinstance(source, str):
        return source.splitlines()
    if isinstance(source, list):
        return "".join(str(part) for part in source).splitlines()
    return []


def _neutralise_magics(*, lines: list[str]) -> list[str]:
    """Comment out IPython syntax that is not Python, preserving line count.

    A cell magic (``%%bash``) makes the whole cell non-Python, so every line is
    commented; line magics (``%matplotlib``) and shell escapes (``!pip``) are
    commented individually. Commenting rather than deleting keeps in-cell line
    numbers true.
    """
    first_code = next((line for line in lines if line.strip()), "")
    if first_code.lstrip().startswith("%%"):
        return [f"{MAGIC_PREFIX} {line}" for line in lines]
    return [
        f"{MAGIC_PREFIX} {line}" if line.lstrip().startswith(("%", "!")) else line for line in lines
    ]


def _parse_failure(*, notebook: str, ordinal: int, error: SyntaxError) -> Violation:
    return Violation(
        file=notebook,
        line=error.lineno or 0,
        rule=NB_000,
        message=f"code cell {ordinal}: does not parse ({error.msg}) — cell skipped",
        fix="Fix the syntax error, or move explore-mode work to an excluded notebook",
    )


def _extract(*, path: Path, notebook: str) -> _Extraction:
    """Flatten *path*'s code cells into one synthetic module with a cell map."""
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
        cells = parsed.get("cells", []) if isinstance(parsed, dict) else []
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        warning = Violation(
            file=notebook,
            line=0,
            rule=NB_000,
            message="notebook is not valid JSON — skipped entirely",
            fix="Re-save the notebook from Jupyter, or exclude it",
        )
        return _Extraction(source="", spans=(), warnings=(warning,))

    out: list[str] = []
    spans: list[_CellSpan] = []
    warnings: list[Violation] = []
    ordinal = 0
    for cell in cells:
        if not isinstance(cell, dict) or cell.get("cell_type") != "code":
            continue
        ordinal += 1
        lines = _neutralise_magics(lines=_cell_lines(source=cell.get("source")))
        if not any(line.strip() for line in lines):
            continue
        try:
            ast.parse("\n".join(lines))
        except SyntaxError as error:
            warnings.append(_parse_failure(notebook=notebook, ordinal=ordinal, error=error))
            lines = [f"{MAGIC_PREFIX} {line}" for line in lines]
        out.append(f"# --- code cell {ordinal} ---")
        spans.append(_CellSpan(start=len(out) + 1, end=len(out) + len(lines), ordinal=ordinal))
        out.extend(lines)
    return _Extraction(source="\n".join(out) + "\n", spans=tuple(spans), warnings=tuple(warnings))


def _remap(*, finding: Violation, notebook: str, spans: tuple[_CellSpan, ...]) -> Violation:
    """Re-anchor a synthetic-module finding onto the notebook and its cell."""
    span = next((s for s in spans if s.start <= finding.line <= s.end), None)
    line = finding.line - span.start + 1 if span else 0
    prefix = f"code cell {span.ordinal}: " if span else ""
    return Violation(
        file=notebook,
        line=line,
        rule=finding.rule,
        message=f"{prefix}{finding.message}",
        fix=finding.fix,
    )


# Synthetic-module name -> (notebook relative path, its cell spans).
_ModuleMap = dict[str, tuple[str, "tuple[_CellSpan, ...]"]]


def _remap_result(
    *, result: CheckResult, modules: _ModuleMap
) -> tuple[list[Violation], list[Violation]]:
    """Re-anchor one sub-check's findings; findings for unknown files are dropped."""
    remapped: tuple[list[Violation], list[Violation]] = ([], [])
    for bucket, findings in zip(remapped, (result.violations, result.warnings)):
        for finding in findings:
            mapped = modules.get(finding.file)
            if mapped is None:
                continue
            notebook, spans = mapped
            bucket.append(_remap(finding=finding, notebook=notebook, spans=spans))
    return remapped


def _resolve_check(*, name: str) -> Check | None:
    """A registered check by name, importing the lanorme built-in on demand."""
    check = get_check(name)
    if check is None:
        try:
            importlib.import_module(f"lanorme.checks.{name}")
        except ImportError:
            return None
        check = get_check(name)
    return check


@dataclass
class NotebooksCheck:
    """Runs the configured file-scoped checks against notebook code cells."""

    name: str = "notebooks"
    description: str = "Report notebooks pass the same checks as promoted Python"
    enabled: bool = True
    checks: list[str] = field(default_factory=lambda: list(DEFAULT_CHECKS))
    exclude: list[str] = field(default_factory=lambda: ["**/archive/**"])
    respect_ruff_excludes: bool = True
    rules: list[str] = field(
        default_factory=lambda: [
            "NB-000: notebook cell could not be parsed (warning)",
            "NB-001: notebook code cells pass the configured checks "
            "(findings keep their original rule codes)",
        ]
    )

    def configure(self, *, settings: dict[str, object]) -> None:
        enabled = settings.get("enabled")
        if isinstance(enabled, bool):
            self.enabled = enabled
        checks = settings.get("checks")
        if isinstance(checks, list):
            self.checks = [str(item) for item in checks]
        exclude = settings.get("exclude")
        if isinstance(exclude, list):
            self.exclude = [str(item) for item in exclude]
        respect = settings.get("respect_ruff_excludes")
        if isinstance(respect, bool):
            self.respect_ruff_excludes = respect

    def _notebooks(self, *, root: Path) -> list[tuple[Path, str]]:
        """(path, root-relative posix path) for every gated notebook."""
        ruff_patterns = _ruff_excludes(root=root) if self.respect_ruff_excludes else []
        found: list[tuple[Path, str]] = []
        for path in iter_files(root, suffix=".ipynb"):
            relative = path.relative_to(root).as_posix()
            if is_glob_match(relative, self.exclude):
                continue
            if ruff_patterns and _ruff_excluded(relative=relative, patterns=ruff_patterns):
                continue
            found.append((path, relative))
        return found

    def _sub_checks(self) -> list[Check]:
        """The configured checks, minus self and anything tree-scoped."""
        resolved: list[Check] = []
        for name in self.checks:
            if name == self.name:
                continue
            check = _resolve_check(name=name)
            if check is None or getattr(check, "scope", "file") == "tree":
                continue
            resolved.append(check)
        return resolved

    def run(self, *, src_root: str) -> CheckResult:
        if not self.enabled:
            return CheckResult(check=self.name, status=Status.PASS)
        notebooks = self._notebooks(root=Path(src_root))
        violations: list[Violation] = []
        warnings: list[Violation] = []
        if not notebooks:
            return CheckResult(check=self.name, status=Status.PASS)

        with tempfile.TemporaryDirectory(prefix="lanorme-nb-") as scratch:
            scratch_root = Path(scratch)
            modules: _ModuleMap = {}
            for path, relative in notebooks:
                extraction = _extract(path=path, notebook=relative)
                warnings.extend(extraction.warnings)
                if not extraction.spans:
                    continue
                module = "nb__" + relative[: -len(".ipynb")].replace("/", "__") + ".py"
                (scratch_root / module).write_text(extraction.source, encoding="utf-8")
                modules[module] = (relative, extraction.spans)

            for check in self._sub_checks():
                result = check.run(src_root=str(scratch_root))
                found, warned = _remap_result(result=result, modules=modules)
                violations.extend(found)
                warnings.extend(warned)

        status = Status.FAIL if violations else (Status.WARN if warnings else Status.PASS)
        return CheckResult(check=self.name, status=status, violations=violations, warnings=warnings)


register(NotebooksCheck())
