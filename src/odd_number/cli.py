"""Command-line entry points.

One CLI, one front door for the package:

    uv run odd-number prompts                       # print every prompt
    uv run odd-number models                        # the pinned slate
    uv run odd-number endpoints qwen/qwen3.6-27b    # provider tags to pin
    uv run odd-number collect --mock --n 5          # no API key needed
    uv run odd-number collect --model qwen/qwen3.6-27b --n 40
    uv run odd-number audit results/<file>.jsonl    # did the pins hold?
    uv run odd-number grade results/<file>.jsonl

`collect` only accepts models on the pinned slate. That is a deliberate refusal
rather than an omission: an unpinned run cannot be compared against a pinned
one, so allowing a bare slug would let an incomparable results file into
`results/` looking exactly like a comparable one.

Argument parsing lives here and nowhere else; the other modules are importable
library code with no side effects at import time.
"""

from __future__ import annotations

import argparse
import sys
from contextlib import ExitStack
from pathlib import Path

from odd_number.candidates import SLATE, TIER1, Candidate, resolve_candidate
from odd_number.client import build_client
from odd_number.environment import Variant, baseline_variants, build_prompt
from odd_number.grades import grade_records, summarise_by_variant
from odd_number.provenance import audit_pins
from odd_number.rollouts import (
    RolloutRequest,
    append_rollout,
    collect_rollout,
    load_completed_keys,
    read_rollouts,
)
from odd_number.sampling import DEFAULT_SAMPLING, SamplingParams
from odd_number.settings import PROJECT_ROOT, MissingSettingsError, Settings, load_settings

# Errors in a row before giving up. A bad key or model name fails identically
# every time, and burning the full budget to prove it is an expensive way to
# read the same message twice.
CONSECUTIVE_FAILURE_LIMIT = 3

#: Stands in for a slate member under --mock, so the mock path exercises the
#: same code shape as a live run rather than a special case of it.
MOCK_CANDIDATE = Candidate(
    slug="mock",
    snapshot="mock",
    provider="mock",
    hf_id="mock",
    params_b=0.0,
    quantization="none",
)


def require_settings() -> Settings | None:
    """Load settings, printing the fix rather than a traceback when they are absent."""
    try:
        return load_settings()
    except MissingSettingsError as exc:
        print(exc, file=sys.stderr)
        return None


def build_sampling(args: argparse.Namespace) -> SamplingParams:
    """The sampling config for this run, defaults overridden by flags."""
    return SamplingParams(
        temperature=args.temperature,
        top_p=args.top_p,
        top_k=args.top_k,
        max_tokens=args.max_tokens,
    )


def cmd_prompts(_: argparse.Namespace) -> int:
    for variant in (*baseline_variants(), Variant(condition="conflict", field_name="_score")):
        print(f"--- {variant.label} ---")
        print(build_prompt(variant))
        print()
    return 0


def describe_lens(candidate: Candidate) -> str:
    """One line about the candidate's Jacobian lens, verification included."""
    if candidate.lens is None:
        return "none"
    if candidate.lens_matches_served_weights:
        return f"{candidate.lens} (verified)"
    if candidate.lens_ckpt is not None:
        return f"{candidate.lens} (fitted on {candidate.lens_ckpt} — MISMATCH)"
    return f"{candidate.lens} (UNVERIFIED — no source recorded)"


def cmd_models(_: argparse.Namespace) -> int:
    print(f"{'model':<28} {'params':>7} {'quant':<12} {'pinned provider':<16} lens")
    for candidate in SLATE:
        tier = "1" if candidate in TIER1 else "2"
        print(
            f"[{tier}] {candidate.slug:<24} {candidate.params_b:>6.1f}B "
            f"{candidate.quantization:<12} {candidate.provider:<16} {describe_lens(candidate)}"
        )
        print(f"      snapshot: {candidate.snapshot}")
        if candidate.note:
            print(f"      {candidate.note}")
    return 0


def cmd_endpoints(args: argparse.Namespace) -> int:
    """List every endpoint serving a model, so a pin can be chosen or re-checked."""
    settings = require_settings()
    if settings is None:
        return 2
    author, _, slug = args.slug.partition("/")
    with build_client(settings) as client:
        listing = client.endpoints.list(author=author, slug=slug)
    print(f"{'tag':<26} {'quant':<8} {'seed':<5} {'uptime':>7} {'$/Mout':>8}")
    for endpoint in sorted(listing.data.endpoints, key=lambda e: float(e.pricing.completion)):
        supported = endpoint.supported_parameters or []
        uptime = endpoint.uptime_last_30m or 0.0
        out = float(endpoint.pricing.completion) * 1e6
        print(
            f"{endpoint.tag:<26} {endpoint.quantization or '?':<8} "
            f"{str('seed' in supported):<5} {uptime:>6.1f}% {out:>8.2f}"
        )
    return 0


def resolve_results_path(args: argparse.Namespace, results_dir: Path, candidate: Candidate) -> Path:
    if args.out:
        return args.out
    return results_dir / f"odd-number-{candidate.slug.replace('/', '-')}.jsonl"


def plan_collection(
    args: argparse.Namespace, results_dir: Path, candidate: Candidate, sampling: SamplingParams
) -> tuple[Path, list[tuple[Variant, int]]]:
    """Where the rollouts go, and which ones are still missing.

    Split out from `cmd_collect` so the resume arithmetic — the part that
    decides what does *not* get re-run, and therefore what a re-run costs —
    reads on its own rather than buried in the command's control flow.
    """
    out_path = resolve_results_path(args, results_dir, candidate)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    already = load_completed_keys(out_path)
    todo = [
        (variant, i)
        for variant in baseline_variants()
        for i in range(args.n)
        if (variant.label, i) not in already
    ]
    print(f"model    {candidate.slug}")
    print(f"snapshot {candidate.snapshot}")
    print(f"provider {candidate.provider}")
    print(f"sampling {sampling.as_record()}")
    print(f"{len(already)} already collected; {len(todo)} to go -> {out_path}")
    return out_path, todo


def cmd_collect(args: argparse.Namespace) -> int:
    try:
        candidate = MOCK_CANDIDATE if args.mock else resolve_candidate(args.model)
    except KeyError as exc:
        print(exc.args[0], file=sys.stderr)
        return 2

    # Credentials are validated before any file is opened or any prompt built:
    # the most likely failure happens first (observability contract, rule 3).
    # --mock needs no key, so it never constructs Settings at all — requiring a
    # credential to run the credential-free path would defeat its purpose.
    settings: Settings | None = None
    if args.mock:
        results_dir = PROJECT_ROOT / "results"
    else:
        settings = require_settings()
        if settings is None:
            return 2
        results_dir = settings.results_dir

    sampling = build_sampling(args)
    out_path, todo = plan_collection(args, results_dir, candidate, sampling)
    if not todo:
        return 0

    failures = 0
    with ExitStack() as stack:
        # The SDK client is a context manager (no close()); enter it only when
        # there is one, so --mock needs no client at all.
        client = None if args.mock else stack.enter_context(build_client(settings))
        handle = stack.enter_context(out_path.open("a", encoding="utf-8"))
        for position, (variant, index) in enumerate(todo, start=1):
            request = RolloutRequest(
                candidate=candidate, variant=variant, index=index, sampling=sampling
            )
            rollout = collect_rollout(client, request)
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
    if not args.mock:
        print(f"\nnow check the pins held: odd-number audit {out_path}")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    """Check a results file against its own pins. Reads the file, calls no API."""
    if not args.results.is_file():
        print(f"no such results file: {args.results}", file=sys.stderr)
        return 2
    report = audit_pins(args.results)
    print(
        f"{report.checked} successful rollouts: {report.verified} with provenance, "
        f"{report.unverified} without (metadata off, or collected before it was enabled)"
    )
    for problem in report.problems:
        print(f"  MISMATCH {problem}")
    if not report.clean:
        print(
            f"{len(report.problems)} rollouts were not served by what was pinned.",
            file=sys.stderr,
        )
        return 1
    if report.verified:
        print("every verified rollout was served by the pinned provider and snapshot.")
    return 0


def cmd_grade(args: argparse.Namespace) -> int:
    if not args.results.is_file():
        print(f"no such results file: {args.results}", file=sys.stderr)
        return 2
    summary = summarise_by_variant(grade_records(read_rollouts(args.results)))
    print(f"{'variant':<24} {'n':>4} {'parse':>6} {'odd':>4} {'gaming':>8} {'reasoning':>10}")
    for variant, row in summary.items():
        print(
            f"{variant:<24} {row['n']:>4} {row['n_parseable']:>6} {row['odd']:>4} "
            f"{row['gaming_rate']:>8.2%} {row['mean_reasoning_chars']:>10.1f}"
        )
    return 0


def add_sampling_flags(parser: argparse.ArgumentParser) -> None:
    """SamplingParams overrides. Defaults are stated, not implicit — see sampling.py."""
    parser.add_argument("--temperature", type=float, default=DEFAULT_SAMPLING.temperature)
    parser.add_argument("--top-p", type=float, default=DEFAULT_SAMPLING.top_p)
    parser.add_argument(
        "--top-k",
        type=int,
        default=DEFAULT_SAMPLING.top_k,
        help="0 disables (vLLM convention, assumed not confirmed); see sampling.py",
    )
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_SAMPLING.max_tokens)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="odd-number", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("prompts", help="print every prompt variant").set_defaults(func=cmd_prompts)
    sub.add_parser("models", help="the pinned model slate").set_defaults(func=cmd_models)

    endpoints = sub.add_parser("endpoints", help="list provider tags serving a model")
    endpoints.add_argument("slug", help="e.g. qwen/qwen3.6-27b")
    endpoints.set_defaults(func=cmd_endpoints)

    collect = sub.add_parser("collect", help="collect rollouts into JSONL")
    collect.add_argument(
        "--model",
        default="qwen/qwen3.6-27b",
        help="must be on the pinned slate; see `odd-number models`",
    )
    collect.add_argument("--n", type=int, default=40, help="rollouts per variant")
    collect.add_argument("--out", type=Path, default=None)
    collect.add_argument("--mock", action="store_true", help="no API key needed")
    add_sampling_flags(collect)
    collect.set_defaults(func=cmd_collect)

    audit = sub.add_parser("audit", help="check a results file against its pins")
    audit.add_argument("results", type=Path)
    audit.set_defaults(func=cmd_audit)

    grade = sub.add_parser("grade", help="grade a results file")
    grade.add_argument("results", type=Path)
    grade.set_defaults(func=cmd_grade)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
