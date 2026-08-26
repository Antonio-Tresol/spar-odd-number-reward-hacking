"""Command-line entry points.

One CLI, one front door for the package:

    uv run odd-number prompts                       # print every prompt
    uv run odd-number models                        # every pinned model
    uv run odd-number endpoints qwen/qwen3.6-27b    # provider tags to pin
    uv run odd-number collect --mock --n 5          # no API key needed
    uv run odd-number collect --model qwen/qwen3.6-27b --n 40
    uv run odd-number audit results/<file>.jsonl    # did the pins hold?
    uv run odd-number grade results/<file>.jsonl    # literal answers only, no key
    uv run odd-number grade results/<file>.jsonl --judge   # prose answers via the judge
    uv run odd-number validate-judge                # agreement on hand-labelled fixtures
    uv run odd-number export-traces --out <dir>     # every trace as Markdown chunks
    uv run odd-number build-explainer               # explainers/odd-number-traces.html

`collect` refuses models that are not pinned: an unpinned results file would
look exactly like a pinned one and could not be compared with it.

Argument parsing lives here and nowhere else; the other modules are
importable library code with no side effects at import time.
"""

from __future__ import annotations

import argparse
import sys
from contextlib import ExitStack
from pathlib import Path

from odd_number.answers import AnswerJudge, judge_cache_path, read_fixtures, validate_judge
from odd_number.client import build_client
from odd_number.environment import (
    DESCRIPTIONS,
    PARAPHRASES,
    Treatment,
    baseline_treatments,
    build_prompt,
)
from odd_number.explainers import build_trace_explainer
from odd_number.grades import grade_records, summarise_by_treatment
from odd_number.pinned_models import (
    HOSTABLE_MODELS,
    PINNED_MODELS,
    PinnedModel,
    resolve_pinned_model,
)
from odd_number.provenance import audit_pins
from odd_number.rollouts import (
    RolloutRequest,
    append_rollout,
    collect_rollouts,
    load_completed_keys,
    read_rollouts,
)
from odd_number.sampling import DEFAULT_SAMPLING, SamplingParams
from odd_number.settings import PROJECT_ROOT, MissingSettingsError, Settings, load_settings
from odd_number.traces import DEFAULT_MAX_CHARS, export_trace_chunks

# Errors in a row before giving up. A bad key or model name fails identically
# every time, and burning the full budget to prove it is an expensive way to
# read the same message twice.
CONSECUTIVE_FAILURE_LIMIT = 3

#: The hand-labelled set `validate-judge` scores the judge against.
FIXTURES_PATH = PROJECT_ROOT / "data" / "answer-fixtures.jsonl"

#: Stands in for a pinned model under --mock, so the mock path exercises the
#: same code shape as a live run rather than a special case of it.
MOCK_MODEL = PinnedModel(
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
    treatments = [
        *baseline_treatments(),
        Treatment(condition="conflict", field_name="_score"),
        *(Treatment(condition="conflict", paraphrase=key) for key in PARAPHRASES),
        *(Treatment(condition="conflict", description=key) for key in DESCRIPTIONS),
    ]
    for treatment in treatments:
        print(f"--- {treatment.label} ---")
        print(build_prompt(treatment))
        print()
    return 0


def describe_lens(model: PinnedModel) -> str:
    """One line about the model's Jacobian lens, verification included."""
    if model.lens is None:
        return "none"
    if model.lens_matches_served_weights:
        return f"{model.lens} (verified)"
    if model.lens_ckpt is not None:
        return f"{model.lens} (fitted on {model.lens_ckpt} — MISMATCH)"
    return f"{model.lens} (UNVERIFIED — no source recorded)"


def cmd_models(_: argparse.Namespace) -> int:
    print(f"{'model':<28} {'params':>7} {'quant':<12} {'pinned provider':<16} lens")
    for model in PINNED_MODELS:
        role = "host" if model in HOSTABLE_MODELS else "screen"
        params = "?" if model.params_b is None else f"{model.params_b:.1f}B"
        print(
            f"[{role:<6}] {model.slug:<24} {params:>7} "
            f"{model.quantization:<12} {model.provider:<16} {describe_lens(model)}"
        )
        print(f"      snapshot: {model.snapshot}")
        if model.note:
            print(f"      {model.note}")
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


def resolve_results_path(args: argparse.Namespace, results_dir: Path, model: PinnedModel) -> Path:
    """One file per (model, paraphrase, description), so each grades on its own."""
    if args.out:
        return args.out
    suffix = "".join(f"-{key}" for key in (args.paraphrase, args.description) if key is not None)
    return results_dir / f"odd-number-{model.slug.replace('/', '-')}{suffix}.jsonl"


def plan_collection(
    args: argparse.Namespace, results_dir: Path, model: PinnedModel, sampling: SamplingParams
) -> tuple[Path, list[tuple[Treatment, int]]]:
    """Where the rollouts go, and which ones are still missing.

    Split out from `cmd_collect` so the resume arithmetic — the part that
    decides what does *not* get re-run, and therefore what a re-run costs —
    reads on its own rather than buried in the command's control flow.
    """
    out_path = resolve_results_path(args, results_dir, model)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    already = load_completed_keys(out_path)
    treatments = [
        treatment
        for treatment in baseline_treatments(args.paraphrase, args.description)
        if args.arm == "both" or treatment.condition == args.arm
    ]
    todo = [
        (treatment, i)
        for treatment in treatments
        for i in range(args.n)
        if (treatment.label, i) not in already
    ]
    print(f"model    {model.slug}")
    print(f"snapshot {model.snapshot}")
    print(f"provider {model.provider}")
    print(f"sampling {sampling.as_record()}")
    print(f"{len(already)} already collected; {len(todo)} to go -> {out_path}")
    return out_path, todo


def cmd_collect(args: argparse.Namespace) -> int:
    try:
        model = MOCK_MODEL if args.mock else resolve_pinned_model(args.model)
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
    out_path, todo = plan_collection(args, results_dir, model, sampling)
    if not todo:
        return 0

    requests = [
        RolloutRequest(model=model, treatment=treatment, index=index, sampling=sampling)
        for treatment, index in todo
    ]
    failures = 0
    with ExitStack() as stack:
        # The SDK client is a context manager (no close()); enter it only when
        # there is one, so --mock needs no client at all.
        client = None if args.mock else stack.enter_context(build_client(settings))
        handle = stack.enter_context(out_path.open("a", encoding="utf-8"))
        rollouts = collect_rollouts(client, requests, workers=args.workers)
        for position, rollout in enumerate(rollouts, start=1):
            append_rollout(handle, rollout)
            if rollout.error:
                failures += 1
                print(f"  [{position}/{len(todo)}] {rollout.treatment} ERROR {rollout.error}")
                if failures >= CONSECUTIVE_FAILURE_LIMIT:
                    print(f"{failures} failures in a row; stopping.", file=sys.stderr)
                    return 1
            else:
                failures = 0
                print(
                    f"  [{position}/{len(todo)}] {rollout.treatment} -> {rollout.response[:40]!r}"
                )
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
    records = read_rollouts(args.results)
    if args.judge:
        settings = require_settings()
        if settings is None:
            return 2
        with build_client(settings) as client:
            with AnswerJudge(client, judge_cache_path(args.results)) as judge:
                graded = grade_records(records, read_answer=judge.read_answer)
                print(f"judge: {judge.calls} new judgements -> {judge.cache_path}")
    else:
        graded = grade_records(records)
    summary = summarise_by_treatment(graded)
    print(
        f"{'treatment':<24} {'n':>4} {'parse':>6} {'odd':>4} {'gaming':>8} "
        f"{'95% CI':>18} {'reasoning':>10}"
    )
    for treatment, row in summary.items():
        interval = f"[{row['gaming_ci95_low']:.2%}, {row['gaming_ci95_high']:.2%}]"
        print(
            f"{treatment:<24} {row['n']:>4} {row['n_parseable']:>6} {row['odd']:>4} "
            f"{row['gaming_rate']:>8.2%} {interval:>18} {row['mean_reasoning_chars']:>10.1f}"
        )
    readable = sum(row["n_readable_cot"] for row in summary.values())
    judged = sum(row["n_judged"] for row in summary.values())
    total = sum(row["n"] for row in summary.values())
    print(f"\nreadable chain of thought (reasoning.text): {readable}/{total} rollouts")
    print(f"answers read by the judge rather than literally: {judged}/{total}")
    return 0


def cmd_validate_judge(args: argparse.Namespace) -> int:
    """Score the judge against the hand-labelled fixtures. Exit 1 on any disagreement."""
    if not args.fixtures.is_file():
        print(f"no such fixture file: {args.fixtures}", file=sys.stderr)
        return 2
    settings = require_settings()
    if settings is None:
        return 2
    fixtures = read_fixtures(args.fixtures)
    with build_client(settings) as client:
        with AnswerJudge(client, judge_cache_path(args.fixtures)) as judge:
            verdicts = validate_judge(judge.read_answer, fixtures)
    agreed = sum(1 for v in verdicts if v.agrees)
    for verdict in verdicts:
        mark = "ok  " if verdict.agrees else "MISS"
        answer = verdict.answer
        print(
            f"{mark} label={verdict.fixture.number!s:<5} judge={answer.number!s:<5} "
            f"[{answer.source}] {verdict.fixture.note}"
        )
        if not verdict.agrees:
            print(f"       quote={answer.quote!r}")
            print(f"       justification={answer.justification!r}")
    print(f"\nagreement: {agreed}/{len(verdicts)}")
    return 0 if agreed == len(verdicts) else 1


def cmd_export_traces(args: argparse.Namespace) -> int:
    """Write every collected trace, graded from cache, as reader-sized Markdown chunks."""
    paths = export_trace_chunks(args.results_dir, args.out, args.max_chars)
    print(f"{len(paths)} chunks -> {args.out} (manifest.json alongside)")
    return 0


def cmd_build_explainer(args: argparse.Namespace) -> int:
    """Build the trace explainer page from results/, results/trace-readings/ and notes/trace-syntheses/."""
    out = build_trace_explainer(args.results_dir, args.readings_dir, args.syntheses_dir, args.out)
    print(f"{out} ({out.stat().st_size / 1e6:.1f} MB)")
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

    sub.add_parser("prompts", help="print every prompt treatment").set_defaults(func=cmd_prompts)
    sub.add_parser("models", help="every pinned model").set_defaults(func=cmd_models)

    endpoints = sub.add_parser("endpoints", help="list provider tags serving a model")
    endpoints.add_argument("slug", help="e.g. qwen/qwen3.6-27b")
    endpoints.set_defaults(func=cmd_endpoints)

    collect = sub.add_parser("collect", help="collect rollouts into JSONL")
    collect.add_argument(
        "--model",
        default="qwen/qwen3.6-27b",
        help="must be a pinned model; see `odd-number models`",
    )
    collect.add_argument("--n", type=int, default=40, help="rollouts per treatment")
    collect.add_argument(
        "--paraphrase",
        choices=sorted(PARAPHRASES),
        default=None,
        help="reword the instruction line (see `odd-number prompts`); default is the post's verbatim text",
    )
    collect.add_argument(
        "--description",
        choices=sorted(DESCRIPTIONS),
        default=None,
        help="add one of the post's description labels inside the metadata block",
    )
    collect.add_argument(
        "--arm",
        choices=["both", "conflict", "agree"],
        default="both",
        help="which arm(s) to collect; conflict-only halves the cost of an intervention",
    )
    collect.add_argument("--out", type=Path, default=None)
    collect.add_argument("--mock", action="store_true", help="no API key needed")
    collect.add_argument(
        "--workers",
        type=int,
        default=1,
        help="calls in flight at once; 1 (default) runs strictly in order",
    )
    add_sampling_flags(collect)
    collect.set_defaults(func=cmd_collect)

    audit = sub.add_parser("audit", help="check a results file against its pins")
    audit.add_argument("results", type=Path)
    audit.set_defaults(func=cmd_audit)

    grade = sub.add_parser("grade", help="grade a results file")
    grade.add_argument("results", type=Path)
    grade.add_argument(
        "--judge",
        action="store_true",
        help="send non-literal responses to the pinned judge (needs a key; cached)",
    )
    grade.set_defaults(func=cmd_grade)

    validate = sub.add_parser("validate-judge", help="score the judge on hand-labelled fixtures")
    validate.add_argument("--fixtures", type=Path, default=FIXTURES_PATH)
    validate.set_defaults(func=cmd_validate_judge)

    export = sub.add_parser(
        "export-traces", help="write every trace as Markdown chunks for reading"
    )
    export.add_argument("--results-dir", type=Path, default=PROJECT_ROOT / "results")
    export.add_argument("--out", type=Path, required=True, help="directory for the chunks")
    export.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    export.set_defaults(func=cmd_export_traces)

    explainer = sub.add_parser("build-explainer", help="build the trace explainer page")
    explainer.add_argument("--results-dir", type=Path, default=PROJECT_ROOT / "results")
    explainer.add_argument(
        "--readings-dir", type=Path, default=PROJECT_ROOT / "results" / "trace-readings"
    )
    explainer.add_argument(
        "--syntheses-dir", type=Path, default=PROJECT_ROOT / "notes" / "trace-syntheses"
    )
    explainer.add_argument(
        "--out", type=Path, default=PROJECT_ROOT / "explainers" / "odd-number-traces.html"
    )
    explainer.set_defaults(func=cmd_build_explainer)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
