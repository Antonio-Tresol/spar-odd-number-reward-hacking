"""TENSOR-001/002: shape discipline for tensors.

Both rules target the same failure — a shape bug that does not raise, and so is
found by debugging a wrong number rather than by reading a signature.

    TENSOR-001  a tensor parameter or return annotated with a bare type
                (`Tensor`, `torch.Tensor`, `np.ndarray`) instead of a jaxtyping
                annotation naming its axes. Vectors count: rank 1 is a shape.
    TENSOR-002  a raw shape operation (`.view`, `.reshape`, `.permute`,
                `.transpose`, `.squeeze`, `.unsqueeze`, `.flatten`) where an
                einops call would state the intent and be checkable.  [warning]

Exploratory code is exempt by design — see `exclude` in lanorme.toml and the
two-mode table in the experiment-engineering skill.

Configure:

    [tensors]
    check_shape_ops = false   # silence TENSOR-002 only

Run:
    lanorme check . --check=tensors
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from lanorme import CheckResult, Status, Violation, register

from ._common import scan_tree

BARE_TENSOR_TYPES: Final[frozenset[str]] = frozenset(
    {
        "Tensor",
        "torch.Tensor",
        "ndarray",
        "np.ndarray",
        "numpy.ndarray",
        "FloatTensor",
        "LongTensor",
        "BoolTensor",
        "IntTensor",
    }
)
JAXTYPING_NAMES: Final[frozenset[str]] = frozenset(
    {
        "Float",
        "Int",
        "Bool",
        "Complex",
        "Float32",
        "Float16",
        "BFloat16",
        "Int32",
        "Int64",
        "UInt8",
        "Shaped",
        "Num",
        "Key",
        "PRNGKeyArray",
    }
)
RAW_SHAPE_OPS: Final[frozenset[str]] = frozenset(
    {
        "view",
        "reshape",
        "permute",
        "transpose",
        "squeeze",
        "unsqueeze",
        "flatten",
    }
)
TENSOR_001: Final[str] = "TENSOR-001: tensor annotations name their axes via jaxtyping"
TENSOR_002: Final[str] = "TENSOR-002: shape operations use einops rather than raw reshaping"
JAXTYPING_FIX: Final[str] = (
    'Annotate with jaxtyping, e.g. Float[Tensor, "batch seq d_model"] '
    '— vectors too: Float[Tensor, "d_model"]'
)
EINOPS_FIX: Final[str] = (
    'Use einops.rearrange with named axes, e.g. rearrange(x, "b s (h d) -> b h s d", h=n_heads)'
)


TENSOR_LIBRARIES: Final[frozenset[str]] = frozenset(
    {
        "torch",
        "numpy",
        "jax",
        "jaxtyping",
        "einops",
        "tensorflow",
        "flax",
        "equinox",
    }
)


def has_tensor_imports(tree: ast.AST) -> bool:
    """True when the file imports a tensor library.

    Without this gate the rules fire on any object that happens to expose a
    method called `.transpose` or `.squeeze`: pandas DataFrames, ORM tables,
    list helpers, permutation-test utilities. None of them can be rewritten with
    einops, so every such finding was unfixable noise.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name.split(".")[0] in TENSOR_LIBRARIES for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] in TENSOR_LIBRARIES:
                return True
    return False


def annotation_text(node: ast.expr | None) -> str:
    """Source text of an annotation node, or '' when absent."""
    return "" if node is None else ast.unparse(node)


def is_bare_tensor(annotation: str) -> bool:
    """True when the annotation names a tensor type without axis names."""
    stripped = annotation.replace("Optional[", "").replace("]", "").strip()
    return any(part.strip() in BARE_TENSOR_TYPES for part in stripped.replace("|", ",").split(","))


def is_jaxtyped(annotation: str) -> bool:
    return any(annotation.startswith(f"{name}[") for name in JAXTYPING_NAMES)


def is_missing_axis_names(annotation: str) -> bool:
    return bool(annotation) and not is_jaxtyped(annotation) and is_bare_tensor(annotation)


def check_arguments(node: ast.FunctionDef | ast.AsyncFunctionDef, file: str) -> list[Violation]:
    found: list[Violation] = []
    args = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
    for arg in args:
        annotation = annotation_text(arg.annotation)
        if is_missing_axis_names(annotation):
            found.append(
                Violation(
                    file=file,
                    line=arg.lineno,
                    rule=TENSOR_001,
                    message=f"Parameter '{arg.arg}' annotated `{annotation}` without axis names",
                    fix=JAXTYPING_FIX,
                )
            )
    return found


def check_return(node: ast.FunctionDef | ast.AsyncFunctionDef, file: str) -> list[Violation]:
    annotation = annotation_text(node.returns)
    if not is_missing_axis_names(annotation):
        return []
    return [
        Violation(
            file=file,
            line=node.lineno,
            rule=TENSOR_001,
            message=f"Return of '{node.name}' annotated `{annotation}` without axis names",
            fix=JAXTYPING_FIX,
        )
    ]


def check_shape_ops(tree: ast.AST, file: str) -> list[Violation]:
    found: list[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in RAW_SHAPE_OPS:
            continue
        found.append(
            Violation(
                file=file,
                line=node.lineno,
                rule=TENSOR_002,
                message=f"`.{node.func.attr}(...)` reshapes without naming axes",
                fix=EINOPS_FIX,
            )
        )
    return found


@dataclass
class TensorsCheck:
    """jaxtyping annotations and einops operations on tensors."""

    name: str = "tensors"
    description: str = "Tensor shape discipline: jaxtyping annotations and einops operations"
    enabled: bool = True
    check_shape_ops: bool = True
    rules: list[str] = field(
        default_factory=lambda: [
            "TENSOR-001: tensor annotations name their axes via jaxtyping",
            "TENSOR-002: shape operations use einops rather than raw reshaping (warning)",
        ]
    )

    def configure(self, *, settings: dict[str, object]) -> None:
        enabled = settings.get("enabled")
        if isinstance(enabled, bool):
            self.enabled = enabled
        shape_ops = settings.get("check_shape_ops")
        if isinstance(shape_ops, bool):
            self.check_shape_ops = shape_ops

    def _scan_file(self, path: Path, file: str) -> tuple[list[Violation], list[Violation]]:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, ValueError):
            return [], []
        if not has_tensor_imports(tree):
            return [], []
        violations: list[Violation] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                violations.extend(check_arguments(node, file))
                violations.extend(check_return(node, file))
        warnings = check_shape_ops(tree, file) if self.check_shape_ops else []
        return violations, warnings

    def run(self, *, src_root: str) -> CheckResult:
        if not self.enabled:
            return CheckResult(check=self.name, status=Status.PASS)
        return scan_tree(name=self.name, src_root=src_root, pattern="*.py", scan=self._scan_file)


register(TensorsCheck())
