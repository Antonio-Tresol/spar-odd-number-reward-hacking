"""Command-line entry points.

One CLI, three subcommands, so the package has a single front door:

    uv run odd-number prompts                       # print every prompt
    uv run odd-number collect --mock --n 5          # no API key needed
    uv run odd-number collect --model deepseek/deepseek-r1 --n 40
    uv run odd-number grade results/<file>.jsonl

Argument parsing lives here and nowhere else; the other modules are importable
library code with no side effects at import time.
"""

from __future__ import annotations

import argparse
import sys
from contextlib import ExitStack
from pathlib import Path

from .client import build_client
from .collect import append_rollout, done_keys, load_dotenv, run_one
from .env import Variant, baseline_pair, build_prompt
from .grading import grade_records, load, summarise

# Errors in a row before giving up. A bad key or model name fails identically
# every time, and burning the full budget to prove it is an expensive way to
# read the same message twice.
CONSECUTIVE_FAILURE_LIMIT = 3


def project_root() -> Path:
    """Repo root, derived from this file rather than the working directory."""
    return Path(__file__).resolve().parent.parent.parent


def cmd_prompts(_: argparse.Namespace) -> int:
    for variant in (*baseline_pair(), Variant(condition="conflict", field_name="_score")):
        print(f"--- {variant.label} ---")
        print(build_prompt(variant))
        print()
    return 0


def resolve_out_path(args: argparse.Namespace, root: Path) -> Path:
    if args.out:
        return args.out
    slug = "mock" if args.mock else args.model.replace("/", "-")
    return root / "results" / f"odd-number-{slug}.jsonl"


def cmd_collect(args: argparse.Namespace) -> int:
    root = project_root()
    load_dotenv(root)

    out_path = resolve_out_path(args, root)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    already = done_keys(out_path)
    todo = [
        (variant, i)
        for variant in baseline_pair()
        for i in range(args.n)
        if (variant.label, i) not in already
    ]
    print(f"{len(already)} already collected; {len(todo)} to go -> {out_path}")
    if not todo:
        return 0

    try:
        client = None if args.mock else build_client()
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 2

    failures = 0
    with ExitStack() as stack:
        # The SDK client is a context manager (no close()); enter it only when
        # there is one, so --mock needs no client at all.
        if client is not None:
            stack.enter_context(client)
        handle = stack.enter_context(out_path.open("a", encoding="utf-8"))
        for position, (variant, index) in enumerate(todo, start=1):
            rollout = run_one(client, variant, index, args.model)
            append_rollout(handle, rollout)
            if rollout.error:
                failures += 1
                print(f"  [{position}/{len(todo)}] {variant.label} ERROR {rollout.error}")
                if failures >= CONSECUTIVE_FAILURE_LIMIT:
                    print(f"{failures} failures in a row; stopping.", file=sys.stderr)
                    return 1
            else:
                failures = 0
                print(f"  [{position}/{len(todo)}] {variant.label} -> {rollout.response[:40]!r}")
    return 0


def cmd_grade(args: argparse.Namespace) -> int:
    if not args.results.is_file():
        print(f"no such results file: {args.results}", file=sys.stderr)
        return 2
    summary = summarise(grade_records(load(args.results)))
    print(f"{'variant':<24} {'n':>4} {'parse':>6} {'odd':>4} {'gaming':>8} {'reasoning':>10}")
    for variant, row in summary.items():
        print(
            f"{variant:<24} {row['n']:>4} {row['n_parseable']:>6} {row['odd']:>4} "
            f"{row['gaming_rate']:>8.2%} {row['mean_reasoning_chars']:>10.1f}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="odd-number", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("prompts", help="print every prompt variant").set_defaults(func=cmd_prompts)

    collect = sub.add_parser("collect", help="collect rollouts into JSONL")
    collect.add_argument("--model", default="deepseek/deepseek-r1")
    collect.add_argument("--n", type=int, default=40, help="rollouts per variant")
    collect.add_argument("--out", type=Path, default=None)
    collect.add_argument("--mock", action="store_true", help="no API key needed")
    collect.set_defaults(func=cmd_collect)

    grade = sub.add_parser("grade", help="grade a results file")
    grade.add_argument("results", type=Path)
    grade.set_defaults(func=cmd_grade)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
