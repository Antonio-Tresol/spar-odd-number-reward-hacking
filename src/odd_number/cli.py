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
    uv run odd-number interview --list --model moonshotai/kimi-k3 --parity odd
    uv run odd-number interview --session k1 --model moonshotai/kimi-k3 \
        --source odd-number-moonshotai-kimi-k3.jsonl --treatment conflict-grader --index 0
    uv run odd-number interview --session k1 --observe "bare integer, no hedging" --quote "1"
    uv run odd-number interview --session k1 --say "Why 7?" --because "tests the reward account"
    uv run odd-number interview --session k1 --show

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

from odd_number.answers import (
    AnswerJudge,
    judge_cache_path,
    read_answer_literally,
    read_fixtures,
    validate_judge,
)
from odd_number.branch_curves import branch_curve_figure, read_branch_curve
from odd_number.branches import (
    Resampler,
    ResampleRequest,
    append_resample,
    choose_branch_points,
    find_branch_candidates,
    find_source_rollout,
    find_treatment_prompt,
    split_sentences,
)
from odd_number.branches import load_completed_keys as branch_completed_keys
from odd_number.chat_templates import TemplateError, resolve_template
from odd_number.client import build_client, build_http_client
from odd_number.environment import (
    DESCRIPTIONS,
    PARAPHRASES,
    Treatment,
    baseline_treatments,
    build_prompt,
)
from odd_number.explainers import build_trace_explainer
from odd_number.figures import AGREE_ARM, CONFLICT_ARM, gaming_rate_figure, gaming_rates
from odd_number.grades import classify_parity, grade_records, summarise_by_treatment
from odd_number.interviews import (
    SEED_REASONING_MODES,
    SEED_REASONING_SHOWN,
    SEED_REASONING_WITHHELD,
    EmptyRationaleError,
    Interview,
    MissingInterviewerError,
    QuoteNotFoundError,
    ReasoningNotReplayableError,
    UnobservedAnswerError,
    append_turn,
    ask_question,
    build_observation,
    build_seed_turns,
    find_seed_traces,
    interview_path,
    open_for_append,
    read_interview,
    render_interview,
    select_seed_trace,
)
from odd_number.pinned_models import (
    HOSTABLE_MODELS,
    PINNED_MODELS,
    PinnedModel,
    resolve_pinned_model,
)
from odd_number.provenance import audit_pins
from odd_number.rollouts import (
    RolloutRecord,
    RolloutRequest,
    append_rollout,
    collect_rollouts,
    load_completed_keys,
    read_rollouts,
)
from odd_number.sampling import DEFAULT_SAMPLING, SamplingParams
from odd_number.settings import PROJECT_ROOT, MissingSettingsError, Settings, load_settings
from odd_number.traces import DEFAULT_MAX_CHARS, export_trace_chunks, load_traces, skipped_files

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
    for path in skipped_files(args.results_dir):
        print(f"not rollouts, so not in the corpus: {path.name}")
    out = build_trace_explainer(args.results_dir, args.readings_dir, args.syntheses_dir, args.out)
    print(f"{out} ({out.stat().st_size / 1e6:.1f} MB)")
    return 0


def list_seed_traces(args: argparse.Namespace) -> int:
    """Print every rollout of one model that an interview could start from."""
    if not args.model:
        print("--list needs --model", file=sys.stderr)
        return 2
    traces = find_seed_traces(args.results_dir, args.model, args.parity)
    label = f" with {args.parity} answers" if args.parity else ""
    print(f"{len(traces)} seedable rollouts for {args.model}{label}")
    for trace in traces:
        print(
            f"  {trace.file:52s} {trace.treatment:28s} #{trace.index:<4d}"
            f" {trace.parity:4s} n={trace.number} cot={len(trace.reasoning)}"
        )
    return 0


def seed_interview(args: argparse.Namespace, path: Path, interviewer: str) -> int:
    """Open a session on one finished rollout.

    Seeding is its own invocation. Asking in the same command could never work:
    the observation guard always fires on the replayed answer, so the question
    would be refused after the file had already been written.
    """
    missing = [f"--{name}" for name in ("model", "source", "treatment") if not getattr(args, name)]
    if args.index is None:
        missing.append("--index")
    if not interviewer:
        missing.append("--interviewer")
    if missing:
        print(f"starting a session needs {', '.join(missing)}", file=sys.stderr)
        return 2
    model = resolve_pinned_model(args.model)
    trace = select_seed_trace(
        find_seed_traces(args.results_dir, args.model, None),
        args.source,
        args.treatment,
        args.index,
    )
    if trace is None:
        print(f"no rollout {args.source} {args.treatment} #{args.index}", file=sys.stderr)
        return 1
    try:
        seeded = build_seed_turns(args.session, model, trace, interviewer, args.seed_reasoning)
    except (MissingInterviewerError, ReasoningNotReplayableError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 2
    with open_for_append(path) as handle:
        for turn in seeded:
            append_turn(handle, turn)
    print(
        f"{args.session}: {model.slug} answered {trace.number} ({trace.parity})"
        f" to {trace.treatment} #{trace.index};"
        f" its chain of thought is {args.seed_reasoning} to the model"
    )
    if trace.reasoning and not args.hide_reasoning:
        print(
            f"\n--- its original chain of thought, {len(trace.reasoning)} chars ---\n"
            f"{trace.reasoning}\n--- end ---"
        )
    return 0


def observe_answer(
    args: argparse.Namespace, path: Path, interview: Interview, interviewer: str
) -> int:
    """Record the interviewer's note on one turn, citations checked."""
    try:
        note = build_observation(
            interview,
            args.observe,
            interviewer,
            quotes=args.quote,
            tags=args.tag,
            about_turn=args.about,
        )
    except (MissingInterviewerError, QuoteNotFoundError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 2
    with open_for_append(path) as handle:
        append_turn(handle, note)
    print(f"noted on turn {note.observes_turn}: quotes={len(note.quotes)}, tags={note.tags}")
    return 0


def ask_interview_question(
    args: argparse.Namespace, path: Path, interview: Interview, interviewer: str
) -> int:
    """Put one question to the model and append both turns."""
    if interview.cost_usd >= args.budget:
        print(
            f"STOP: {args.session} has spent ${interview.cost_usd:.3f} of ${args.budget:.2f}",
            file=sys.stderr,
        )
        return 1
    settings = require_settings()
    if settings is None:
        return 1
    try:
        with build_client(settings) as client:
            question, answer = ask_question(
                client,
                resolve_pinned_model(interview.model),
                interview,
                args.say,
                args.because,
                build_sampling(args),
                interviewer,
            )
    except (EmptyRationaleError, MissingInterviewerError, UnobservedAnswerError) as exc:
        print(exc, file=sys.stderr)
        return 2
    with open_for_append(path) as handle:
        append_turn(handle, question)
        append_turn(handle, answer)
    if answer.error:
        print(f"ERROR: {answer.error}", file=sys.stderr)
        return 1
    if answer.reasoning and not args.hide_reasoning:
        print(f"--- chain of thought ---\n{answer.reasoning}\n--- answer ---")
    print(answer.content)
    spent = interview.cost_usd + answer.cost_usd
    print(f"\n[{args.session}: ${spent:.3f} of ${args.budget:.2f}]", file=sys.stderr)
    return 0


def cmd_interview(args: argparse.Namespace) -> int:
    """Dispatch to one interview action: list, show, seed, observe, or ask.

    One action per invocation: what to ask next depends on the last answer, so a
    batch would not be an interview.
    """
    if args.list:
        return list_seed_traces(args)
    if not args.session:
        print("--session is required unless --list is used", file=sys.stderr)
        return 2
    path = interview_path(args.results_dir, args.session)
    interview = read_interview(path)
    if args.show:
        if interview is None:
            print(f"no interview at {path}", file=sys.stderr)
            return 1
        print(render_interview(interview))
        return 0
    # A resumed session inherits who was asking, so attribution cannot be lost by
    # omitting the flag later. An explicit flag still wins: a second interviewer
    # taking over is a real thing to record.
    interviewer = (args.interviewer or (interview.interviewer if interview else "")).strip()
    if interview is None:
        return seed_interview(args, path, interviewer)
    if args.observe:
        return observe_answer(args, path, interview, interviewer)
    if args.say:
        return ask_interview_question(args, path, interview, interviewer)
    print("--say, --observe, --show or a seeding run is required", file=sys.stderr)
    return 2


def list_branch_candidates(args: argparse.Namespace) -> int:
    """Print every rollout in the source file that a sweep could branch from."""
    candidates = find_branch_candidates(args.source, args.treatment)
    if not candidates:
        print(f"no {args.treatment!r} rollouts in {args.source.name}", file=sys.stderr)
        return 2
    print(f"{'idx':>4} {'parity':<12} {'answer':>7} {'chars':>7} {'sentences':>10}")
    for candidate in sorted(candidates, key=lambda c: -c.reasoning_chars):
        print(
            f"{candidate.index:>4} {candidate.parity:<12} "
            f"{str(candidate.answer):>7} {candidate.reasoning_chars:>7} "
            f"{candidate.sentences:>10}"
        )
    return 0


def resolve_branch_path(args: argparse.Namespace, model: PinnedModel) -> Path:
    """One file per (model, source trace, prompt), so each curve stands alone.

    A cross-prompt sweep takes its own file. Appending it to the same-prompt
    sweep's file would put two conditions on one curve, and resume keys on
    `(sentences_kept, index)`, so the two would also silently cancel each other.
    """
    if args.out:
        return args.out
    stem = f"{model.slug.replace('/', '-')}-{args.treatment}-{args.index}"
    if args.prompt_from is not None:
        stem = f"{stem}-under-{args.prompt_treatment or args.treatment}"
    return PROJECT_ROOT / "results" / "branches" / f"branch-{stem}.jsonl"


def resolve_branch_prompt(args: argparse.Namespace, record: RolloutRecord) -> tuple[str, str, str]:
    """Which prompt the resamples run under, and where it came from.

    Without `--prompt-from` this is the branched rollout's own prompt, which is
    an ordinary sweep. With it, the prefix stays and the prompt is swapped for
    another condition's, which is the read that separates resolving a conflict
    from deliberating less: a prefix that goes odd under its own prompt either
    still does under the affirming prompt, or does not.

    Raises:
        KeyError: when the prompt file has no such treatment, or more than one
            prompt under it.
    """
    if args.prompt_from is None:
        return args.source.name, args.treatment, record.get("prompt") or ""
    treatment = args.prompt_treatment or args.treatment
    return (
        args.prompt_from.name,
        treatment,
        find_treatment_prompt(args.prompt_from, treatment),
    )


def run_branch_sweep(args: argparse.Namespace, model: PinnedModel) -> int:
    """Resample one trace at every chosen branch point, appending as rows land."""
    try:
        record = find_source_rollout(args.source, args.treatment, args.index)
        template = resolve_template(model.slug)
    except (KeyError, TemplateError) as exc:
        print(exc.args[0], file=sys.stderr)
        return 2

    reasoning = record.get("reasoning") or ""
    if not reasoning:
        print(f"rollout {args.index} has no chain of thought to branch", file=sys.stderr)
        return 2

    sentences = split_sentences(reasoning)
    branches = choose_branch_points(sentences, args.points)
    answer = read_answer_literally(record.get("response") or "").number
    try:
        prompt_file, prompt_treatment, user_prompt = resolve_branch_prompt(args, record)
    except KeyError as exc:
        print(exc.args[0], file=sys.stderr)
        return 2
    request = ResampleRequest(
        source_file=args.source.name,
        source_index=args.index,
        source_parity=classify_parity(answer),
        treatment=args.treatment,
        prompt_file=prompt_file,
        prompt_treatment=prompt_treatment,
        user_prompt=user_prompt,
        sampling=build_sampling(args),
    )

    out_path = resolve_branch_path(args, model)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = branch_completed_keys(out_path)
    total = len(branches) * args.rollouts
    print(f"source   {args.source.name} index {args.index} -> {request.source_parity} {answer}")
    print(f"trace    {len(reasoning)} chars, {len(sentences)} sentences")
    if request.is_cross_prompt:
        print(f"prompt   {prompt_treatment} from {prompt_file} (cross-prompt)")
    print(f"branches {[b.sentences_kept for b in branches]}")
    print(f"{len(done)} of {total} already done -> {out_path}")

    with out_path.open("a", encoding="utf-8") as handle, build_http_client() as client:
        resampler = Resampler(client=client, template=template, model=model)
        for resample in resampler.sweep(branches, request, args.rollouts, done, args.workers):
            append_resample(handle, resample)
            note = resample.error or f"{resample.parity} {resample.answer}"
            print(f"  [kept {resample.sentences_kept:>4} #{resample.index:>3}] {note}")
    return 0


def cmd_branch(args: argparse.Namespace) -> int:
    if args.list:
        return list_branch_candidates(args)
    if args.index is None:
        print("--index is required unless --list is given", file=sys.stderr)
        return 2
    try:
        model = resolve_pinned_model(args.model)
    except KeyError as exc:
        print(exc.args[0], file=sys.stderr)
        return 2
    return run_branch_sweep(args, model)


def add_output_parsers(sub: argparse._SubParsersAction) -> None:
    """`export-traces` and `build-explainer`: the two commands that write documents."""
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


def cmd_branch_figure(args: argparse.Namespace) -> int:
    """Draw one or more branch sweeps as P(odd) against prefix length."""
    if len(args.sweep) != len(args.label):
        print("--sweep and --label must be given the same number of times", file=sys.stderr)
        return 2
    curves = [
        read_branch_curve(path, label) for path, label in zip(args.sweep, args.label, strict=True)
    ]
    for curve in curves:
        covered = sum(rate.trials for rate in curve.rates)
        print(f"{curve.label}: {len(curve.rates)} branch points, {covered} resamples")
    figure = branch_curve_figure(curves, args.title, args.caption)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(args.out, dpi=200, bbox_inches="tight")
    print(f"wrote {args.out}")
    return 0


def cmd_gaming_figure(args: argparse.Namespace) -> int:
    """Draw the per-model odd-answer rate under the conflicting grader."""
    traces = load_traces(args.results_dir)
    conflict = gaming_rates(traces, CONFLICT_ARM)
    agree = gaming_rates(traces, AGREE_ARM)
    if not conflict:
        print(f"no {CONFLICT_ARM!r} traces under {args.results_dir}", file=sys.stderr)
        return 2
    print(f"{len(conflict)} models, {sum(r.parseable for r in conflict)} conflict rollouts")
    figure = gaming_rate_figure(conflict, agree)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(args.out, dpi=200, bbox_inches="tight")
    print(f"wrote {args.out}")
    return 0


def add_gaming_figure_parser(sub: argparse._SubParsersAction) -> None:
    """`gaming-figure`: the per-model rate, as a PNG for a write-up."""
    figure = sub.add_parser("gaming-figure", help="plot the odd-answer rate per model")
    figure.add_argument("--results-dir", type=Path, default=PROJECT_ROOT / "results")
    figure.add_argument("--out", type=Path, default=PROJECT_ROOT / "figures" / "gaming-rate.png")
    figure.set_defaults(func=cmd_gaming_figure)


def add_branch_figure_parser(sub: argparse._SubParsersAction) -> None:
    """`branch-figure`: the resampling curve, as a PNG for a write-up."""
    figure = sub.add_parser("branch-figure", help="plot P(odd) against prefix length")
    figure.add_argument("--sweep", type=Path, action="append", required=True)
    figure.add_argument("--label", action="append", required=True)
    figure.add_argument("--title", default="Where the answer is decided")
    figure.add_argument("--caption", default="")
    figure.add_argument("--out", type=Path, default=PROJECT_ROOT / "figures" / "branch-curve.png")
    figure.set_defaults(func=cmd_branch_figure)


def add_branch_parser(sub: argparse._SubParsersAction) -> None:
    """`branch`: resample one trace from truncation points (arXiv 2510.27484)."""
    branch = sub.add_parser(
        "branch",
        help="resample a chain of thought from truncation points",
        description=(
            "Hold the first N sentences of a real trace as a prefix and resample "
            "what follows, at several N. The shift in the odd rate across N is "
            "where the answer was decided. Prefixes are always truncations of a "
            "collected trace, never written by hand."
        ),
    )
    branch.add_argument("--source", type=Path, required=True, help="a results JSONL file")
    branch.add_argument("--treatment", default="conflict-grader")
    branch.add_argument(
        "--prompt-from",
        type=Path,
        help="continue this trace's prefix under another results file's prompt",
    )
    branch.add_argument(
        "--prompt-treatment",
        help="which treatment's prompt to take from --prompt-from (default: --treatment)",
    )
    branch.add_argument("--list", action="store_true", help="print branchable rollouts and exit")
    branch.add_argument("--index", type=int, help="which rollout in --source to branch")
    branch.add_argument("--model", default="qwen/qwen3.8-27b", help="must have a chat template")
    branch.add_argument("--points", type=int, default=10, help="branch points, both ends included")
    branch.add_argument("--rollouts", type=int, default=30, help="resamples per branch point")
    branch.add_argument("--workers", type=int, default=8, help="calls in flight at once")
    branch.add_argument("--out", type=Path)
    add_sampling_flags(branch)
    branch.set_defaults(func=cmd_branch)


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


def add_interview_parser(sub: argparse._SubParsersAction) -> None:
    """Flags for `interview`. Split out to keep `build_parser` readable."""
    interview = sub.add_parser(
        "interview", help="resume a finished rollout as a conversation and question the model"
    )
    interview.add_argument("--results-dir", type=Path, default=PROJECT_ROOT / "results")
    interview.add_argument(
        "--session", help="session name; the file is results/interviews/<name>.jsonl"
    )
    interview.add_argument("--list", action="store_true", help="list seedable rollouts for --model")
    interview.add_argument("--show", action="store_true", help="print the transcript so far")
    interview.add_argument("--model", help="pinned model slug, to seed a session or to --list")
    interview.add_argument("--parity", choices=["odd", "even"], help="filter --list")
    interview.add_argument("--source", help="results filename to seed from")
    interview.add_argument("--treatment", help="treatment label of the seed rollout")
    interview.add_argument("--index", type=int, help="index of the seed rollout")
    interview.add_argument("--say", help="one question to put to the model")
    interview.add_argument(
        "--because",
        default="",
        help="why this question is being asked; required with --say and recorded on the turn",
    )
    interview.add_argument(
        "--observe",
        help="a note on the model's last turn; required before the next --say",
    )
    interview.add_argument(
        "--quote",
        action="append",
        default=[],
        metavar="TEXT",
        help="verbatim span from the observed turn or its reasoning, repeatable; checked",
    )
    interview.add_argument(
        "--tag",
        action="append",
        default=[],
        metavar="TAG",
        help="tag on an observation, repeatable; no fixed vocabulary",
    )
    interview.add_argument(
        "--about", type=int, help="turn number an --observe is about (default: the model's last)"
    )
    interview.add_argument(
        "--interviewer", default="", help="who is asking: agent name, model, or person"
    )
    interview.add_argument(
        "--seed-reasoning",
        choices=SEED_REASONING_MODES,
        default=SEED_REASONING_SHOWN,
        help=(
            f"{SEED_REASONING_SHOWN}: replay the rollout's chain of thought to the model, "
            f"which needs an endpoint that forwards it. {SEED_REASONING_WITHHELD}: record it "
            "but do not send it. Set at seeding and fixed for the session."
        ),
    )
    interview.add_argument(
        "--hide-reasoning",
        action="store_true",
        help="suppress chains of thought, which are printed by default",
    )
    interview.add_argument(
        "--budget", type=float, default=2.0, help="stop before the next question, USD"
    )
    add_sampling_flags(interview)
    interview.set_defaults(func=cmd_interview)


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
        help="add a description label inside the metadata block; see environment.py "
        "for which are the post's and which are this project's",
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

    add_output_parsers(sub)
    add_branch_parser(sub)
    add_branch_figure_parser(sub)
    add_gaming_figure_parser(sub)
    add_interview_parser(sub)
    return parser


def main() -> int:
    """Run one subcommand.

    Console encoding is loosened first because several commands print model
    text, and a Windows console defaults to cp1252. A chain of thought
    containing one CJK character then raises `UnicodeEncodeError` *after* the
    API call has been paid for, losing the print rather than the data. Replacing
    the character is the right trade: the transcript on disk is UTF-8 either way.
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
