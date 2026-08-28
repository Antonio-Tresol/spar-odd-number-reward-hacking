"""Resampling a chain of thought from truncation points.

Method from Macar et al., "Thought Branches: Interpreting LLM Reasoning Requires
Resampling" (arXiv 2510.27484), section 2.1.1: hold `S_1..S_i` as a prefix,
resample everything after it, and read the shift in the outcome distribution.
Their code resamples through OpenRouter's `/v1/completions`; so does this.

The outcome here is one bit, odd or even, so counterfactual importance is a
difference of proportions and needs none of the paper's embedding or KL
machinery:

    importance(S_i) = P(odd | S_1..S_i) - P(odd | S_1..S_i-1)

Three things this module must not do quietly.

- **Prefixes are truncations of a real trace**, never written by hand. The
  paper's section 3 finds off-policy insertions cluster near zero effect, so a
  hand-written prefix would measure the wrong thing and look like a null.
- **Seeds vary per resample.** A fixed seed across a hundred resamples collapses
  the distribution to a point mass, which reads as "no sentence matters" rather
  than "we sampled once, a hundred times".
- **The prompt is rendered, not assumed.** `chat_templates.py` says why.

The vendor boundary is raw JSON, because the SDK wraps only
`/v1/chat/completions`. It stops at `parse_continuation`, the way a `ChatResult`
stops at `completions.py`: direct indexing, and a shape we cannot read raises
instead of returning a plausible blank.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from random import uniform
from time import monotonic, sleep
from typing import Any, Final, TextIO

import httpx

from odd_number.answers import read_answer_literally
from odd_number.chat_templates import ChatTemplate
from odd_number.grades import classify_parity
from odd_number.pinned_models import PinnedModel, build_routing_body
from odd_number.rollouts import RolloutRecord, read_rollouts
from odd_number.sampling import SamplingParams

COMPLETIONS_URL: Final[str] = "https://openrouter.ai/api/v1/completions"

#: Status codes worth trying again. A sweep submits hundreds of calls at once
#: and the provider rate-limits the opening burst, so without backoff the
#: failures land on whichever branch points were submitted first. That looks
#: exactly like a branch point being special and is not (observed 2026-08-28:
#: 141 of 487 calls lost, all 429, all on the four earliest branch points).
RETRIABLE_STATUS: Final[frozenset[int]] = frozenset({408, 429, 500, 502, 503, 504})
RETRY_ATTEMPTS: Final[int] = 6
RETRY_BASE_S: Final[float] = 2.0
RETRY_MAX_S: Final[float] = 45.0

#: Where one sentence ends: terminal punctuation followed by whitespace, or a
#: blank line. Traces are half prose and half arithmetic, so a paragraph break is
#: as real a boundary as a full stop. Each piece keeps its trailing whitespace,
#: which is what makes rejoining them reproduce the input exactly. A prefix that
#: silently loses a newline is a prefix the model never produced.
SENTENCE_BOUNDARY: Final[re.Pattern[str]] = re.compile(r"(?<=[.!?])\s+|\n\n+")

#: A bare integer, with or without markdown bold. This model wrote no prose
#: answers in 321 graded conflict responses, and 4 of 39 in the first branch
#: probe came back bold, so bold is expected and anything else is not.
BARE_INTEGER: Final[re.Pattern[str]] = re.compile(r"^\**\s*(-?\d+)\s*\**$")

#: What closes the reasoning channel. The answer is whatever follows it.
THINK_CLOSE: Final[str] = "</think>"


class ContinuationShapeError(RuntimeError):
    """The completions endpoint returned a shape this project cannot read."""


@dataclass(frozen=True, slots=True)
class BranchPoint:
    """One truncation of a trace: the first `sentences_kept` sentences.

    `sentences_kept` of 0 is branch position zero, where the model reasons from
    the prompt alone. It is the calibration point: its odd rate should reproduce
    the rate the source run was collected at, and if it does not, nothing further
    along the curve is interpretable.
    """

    sentences_kept: int
    prefix: str

    @property
    def prefix_chars(self) -> int:
        """How much of the trace this prefix carries."""
        return len(self.prefix)


@dataclass(frozen=True, slots=True)
class Continuation:
    """One text completion, in this project's terms. Raw JSON stops here."""

    text: str
    finish_reason: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    served_provider: str | None
    served_model: str | None


@dataclass(frozen=True, slots=True)
class ResampleRequest:
    """What one branch sweep needs beyond the model and the client.

    Carries the source rollout's identity so every row traces back to the trace
    it branched from, and owns seed derivation so a sweep and a resumed sweep
    cannot disagree about it.
    """

    source_file: str
    source_index: int
    source_parity: str
    treatment: str
    prompt_file: str
    prompt_treatment: str
    user_prompt: str
    sampling: SamplingParams

    @property
    def is_cross_prompt(self) -> bool:
        """Whether the prompt comes from somewhere other than the branched trace."""
        return (self.prompt_file, self.prompt_treatment) != (self.source_file, self.treatment)

    def derive_seed(self, sentences_kept: int, index: int) -> int:
        """A stable seed, distinct per branch point and resample.

        Distinct is the requirement, not unpredictable: one seed reused across a
        branch point's resamples is what turns a distribution into a point mass.
        Built from a digest rather than `hash`, which is salted per process and
        would give a resumed run different seeds from the run it resumes.

        A same-prompt sweep keeps the key it had before cross-prompt sweeps
        existed, so a run already on disk resumes against the seeds it was bought
        with. A cross-prompt sweep is a different condition and takes a different
        key, so the two never draw the same sample from the same branch point.
        """
        key = f"{self.source_file}:{self.source_index}:{sentences_kept}:{index}"
        if self.is_cross_prompt:
            key = f"{self.prompt_file}:{self.prompt_treatment}|{key}"
        return int.from_bytes(sha256(key.encode()).digest()[:4]) % (2**31)


@dataclass(frozen=True, slots=True)
class Resample:
    """One resample from one branch point. Written verbatim as a JSONL line.

    Flat, because the consumer is pandas and a flat line is one row.
    """

    source_file: str
    source_index: int
    source_parity: str
    treatment: str
    prompt_file: str
    prompt_treatment: str
    model: str
    snapshot: str
    provider: str
    sentences_kept: int
    prefix_chars: int
    index: int
    seed: int
    sampling: dict[str, Any]
    continuation: str
    answer: int | None
    parity: str
    finish_reason: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    served_provider: str | None
    served_model: str | None
    error: str | None
    elapsed_s: float


def split_sentences(text: str) -> list[str]:
    """Split a trace into sentences that rejoin to the original exactly.

    Exactness is the point: the prefix sent to the model has to be a substring of
    the trace it came from, character for character.
    """
    pieces: list[str] = []
    start = 0
    for match in SENTENCE_BOUNDARY.finditer(text):
        pieces.append(text[start : match.end()])
        start = match.end()
    if start < len(text):
        pieces.append(text[start:])
    return pieces


def choose_branch_points(sentences: Sequence[str], count: int) -> list[BranchPoint]:
    """`count` branch points spread evenly from an empty prefix to the whole trace.

    Both ends are included and both are anchors. Zero sentences kept should
    reproduce the collection-time rate; every sentence kept leaves the model only
    to close its reasoning and answer, so it should reproduce the source trace's
    own answer. A curve whose ends miss those is measuring the harness.

    Raises:
        ValueError: when fewer than the two anchor points are asked for.
    """
    if count < 2:
        raise ValueError(f"need at least the two anchor points, got count={count}")
    total = len(sentences)
    kept = sorted({round(i * total / (count - 1)) for i in range(count)})
    return [BranchPoint(sentences_kept=k, prefix="".join(sentences[:k])) for k in kept]


def select_branch_points(sentences: Sequence[str], kept: Sequence[int]) -> list[BranchPoint]:
    """Branch points at named prefix lengths, for sweeping one span sentence by
    sentence.

    `choose_branch_points` spreads its points over the whole trace, so resolving
    a ten-sentence span to single sentences through it would mean buying every
    other sentence of the trace as well. Naming the lengths buys the span alone.

    Raises:
        ValueError: when a length falls outside the trace, which would silently
            truncate to a prefix the caller did not ask for.
    """
    total = len(sentences)
    outside = sorted({k for k in kept if k < 0 or k > total})
    if outside:
        raise ValueError(f"branch points {outside} are outside a trace of {total} sentences")
    return [BranchPoint(sentences_kept=k, prefix="".join(sentences[:k])) for k in sorted(set(kept))]


def extract_answer(text: str) -> int | None:
    """The bare integer after the reasoning channel closes, or None.

    Strict on purpose. Non-conforming continuations are counted and reported
    rather than sent to `AnswerJudge`: at a hundred resamples per branch point a
    judge pass would cost more than the experiment itself, and this model's
    answers are bare integers throughout the existing corpus.
    """
    if THINK_CLOSE not in text:
        return None
    tail = text.split(THINK_CLOSE, 1)[1].strip()
    match = BARE_INTEGER.match(tail)
    return int(match.group(1)) if match else None


def parse_continuation(payload: dict[str, Any]) -> Continuation:
    """Narrow the endpoint's JSON to a `Continuation`, or refuse.

    Indexing rather than `.get` with a default, for the reason `completions.py`
    gives: a renamed field must raise on the first call instead of coming back
    empty and being counted as an unparseable answer a thousand times over.

    Raises:
        ContinuationShapeError: when the body carries no readable choice or usage.
    """
    try:
        choice = payload["choices"][0]
        text = choice["text"]
        usage = payload["usage"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ContinuationShapeError(
            f"completions response had no readable choice or usage: {exc}. "
            "Update parse_continuation rather than defaulting the field."
        ) from exc
    if not isinstance(text, str):
        raise ContinuationShapeError(f"choice text was {type(text).__name__}, expected str")
    metadata = payload.get("openrouter_metadata") or {}
    endpoints = (metadata.get("endpoints") or {}).get("available") or []
    selected = [endpoint for endpoint in endpoints if endpoint.get("selected")]
    return Continuation(
        text=text,
        finish_reason=choice.get("finish_reason") or "",
        prompt_tokens=usage.get("prompt_tokens", 0),
        completion_tokens=usage.get("completion_tokens", 0),
        cost_usd=usage.get("cost") or 0.0,
        served_provider=selected[0].get("provider") if selected else None,
        served_model=selected[0].get("model") if selected else None,
    )


def request_continuation(
    client: httpx.Client,
    model: PinnedModel,
    prompt: str,
    seed: int,
    sampling: SamplingParams,
) -> Continuation:
    """One text completion against the pinned endpoint.

    `n` is not sent. The endpoint accepts it and returns a single choice anyway,
    even under `require_parameters=True`, so asking for a batch would quietly
    yield one rollout billed as a batch (probed 2026-08-28).

    Raises:
        ContinuationShapeError: on a non-200 response or an unreadable body.
    """
    body: dict[str, Any] = {
        "model": model.snapshot,
        "prompt": prompt,
        "seed": seed,
        "provider": build_routing_body(model.provider),
        **sampling.as_request_kwargs(),
    }
    for attempt in range(RETRY_ATTEMPTS):
        response = client.post(COMPLETIONS_URL, json=body)
        if response.status_code == 200:
            return parse_continuation(response.json())
        if response.status_code not in RETRIABLE_STATUS or attempt == RETRY_ATTEMPTS - 1:
            raise ContinuationShapeError(f"HTTP {response.status_code}: {response.text[:300]}")
        # Full jitter: without it every worker in the pool backs off in step and
        # the burst that caused the rate limit simply repeats a second later.
        sleep(uniform(0.0, min(RETRY_BASE_S * 2**attempt, RETRY_MAX_S)))
    raise ContinuationShapeError("unreachable: retry loop exited without returning")


def collect_resample(
    resampler: "Resampler",
    branch: BranchPoint,
    request: ResampleRequest,
    index: int,
) -> Resample:
    """One resample, capturing errors rather than raising.

    A failure on one call must not kill a sweep of several thousand, so the
    exception lands in the row's `error` field and the sweep continues.
    """
    model = resampler.model
    seed = request.derive_seed(branch.sentences_kept, index)
    prompt = resampler.template.render(request.user_prompt, branch.prefix)
    started = monotonic()
    continuation: Continuation | None = None
    error: str | None = None
    try:
        continuation = request_continuation(resampler.client, model, prompt, seed, request.sampling)
    except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
        error = f"{type(exc).__name__}: {exc}"
    done = continuation or Continuation("", "", 0, 0, 0.0, None, None)
    answer = extract_answer(done.text) if continuation is not None else None
    return Resample(
        source_file=request.source_file,
        source_index=request.source_index,
        source_parity=request.source_parity,
        treatment=request.treatment,
        prompt_file=request.prompt_file,
        prompt_treatment=request.prompt_treatment,
        model=model.slug,
        snapshot=model.snapshot,
        provider=model.provider,
        sentences_kept=branch.sentences_kept,
        prefix_chars=branch.prefix_chars,
        index=index,
        seed=seed,
        sampling=request.sampling.as_record(),
        continuation=done.text,
        answer=answer,
        parity=classify_parity(answer),
        finish_reason=done.finish_reason,
        prompt_tokens=done.prompt_tokens,
        completion_tokens=done.completion_tokens,
        cost_usd=done.cost_usd,
        served_provider=done.served_provider,
        served_model=done.served_model,
        error=error,
        elapsed_s=round(monotonic() - started, 3),
    )


def load_completed_keys(path: Path) -> set[tuple[int, int]]:
    """Branch-point and resample pairs already on disk, so a rerun resumes.

    Rows that recorded an error are not counted as done; they are retried, the
    way `collect` retries a failed rollout.
    """
    if not path.exists():
        return set()
    done: set[tuple[int, int]] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("error") is None:
            done.add((row["sentences_kept"], row["index"]))
    return done


def append_resample(handle: TextIO, resample: Resample) -> None:
    """Write one row and flush, so a kill loses at most the in-flight call."""
    handle.write(json.dumps(asdict(resample), ensure_ascii=False) + "\n")
    handle.flush()


@dataclass(frozen=True, slots=True)
class BranchCandidate:
    """One source rollout, described well enough to choose whether to branch it.

    Selection matters: `Q1.H7.E4.C2` found that gaming and compliant traces carry
    the same arguments and differ in which lean is standing at the end, so a
    trace that never deliberates has no branch point to find.
    """

    index: int
    treatment: str
    answer: int | None
    parity: str
    reasoning_chars: int
    sentences: int


def find_branch_candidates(path: Path, treatment: str) -> list[BranchCandidate]:
    """Every rollout in a results file that could be branched, with its shape.

    Graded by the literal reader only. A response this project's judge would have
    to interpret is not a clean anchor for a curve whose outcome is one bit, so it
    is reported as unparseable and left for the caller to skip.
    """
    candidates: list[BranchCandidate] = []
    for record in read_rollouts(path):
        if record.get("treatment") != treatment or record.get("error"):
            continue
        reasoning = record.get("reasoning") or ""
        answer = read_answer_literally(record.get("response") or "").number
        candidates.append(
            BranchCandidate(
                index=record.get("index", -1),
                treatment=treatment,
                answer=answer,
                parity=classify_parity(answer),
                reasoning_chars=len(reasoning),
                sentences=len(split_sentences(reasoning)),
            )
        )
    return candidates


def find_treatment_prompt(path: Path, treatment: str) -> str:
    """The one user prompt a treatment was collected under, from a results file.

    A cross-prompt sweep continues one condition's prefix under another
    condition's prompt, so the prompt has to come from a file the prefix did not.
    Disagreeing prompts under one treatment label would make that swap
    unreadable, so more than one distinct prompt raises rather than picking.

    Raises:
        KeyError: when the treatment is absent, or its rollouts disagree about
            the prompt.
    """
    prompts = {
        record.get("prompt") or ""
        for record in read_rollouts(path)
        if record.get("treatment") == treatment
    }
    if not prompts:
        raise KeyError(f"no rollout with treatment {treatment!r} in {path.name}")
    if len(prompts) > 1:
        raise KeyError(
            f"treatment {treatment!r} in {path.name} was collected under "
            f"{len(prompts)} different prompts; a cross-prompt sweep needs one"
        )
    return prompts.pop()


def find_source_rollout(path: Path, treatment: str, index: int) -> RolloutRecord:
    """The one rollout a sweep branches from.

    Raises:
        KeyError: when no rollout in the file has that treatment and index.
    """
    for record in read_rollouts(path):
        if record.get("treatment") == treatment and record.get("index") == index:
            return record
    raise KeyError(
        f"no rollout with treatment {treatment!r} and index {index} in {path.name}. "
        "`odd-number branch --list` prints what is there."
    )


@dataclass(frozen=True, slots=True)
class Resampler:
    """What performs a resample: an endpoint, a prompt format, and a pinned model.

    The three travel together on every call and none of them varies within a
    sweep, so they are one object rather than three parameters threaded through
    each function.
    """

    client: httpx.Client
    template: ChatTemplate
    model: PinnedModel

    def sweep(
        self,
        branches: Sequence[BranchPoint],
        request: ResampleRequest,
        rollouts_per_branch: int,
        done: set[tuple[int, int]],
        workers: int = 8,
    ) -> Iterator[Resample]:
        """Every outstanding resample, yielded the moment it lands.

        Yields rather than returns so the caller appends each row as it arrives;
        a kill loses at most what is in flight. Work already on disk is skipped
        via `done`, so a killed sweep resumes rather than re-buying its results.
        """
        todo = [
            (branch, index)
            for branch in branches
            for index in range(rollouts_per_branch)
            if (branch.sentences_kept, index) not in done
        ]
        pool = ThreadPoolExecutor(max_workers=workers)
        try:
            futures = [
                pool.submit(collect_resample, self, branch, request, index)
                for branch, index in todo
            ]
            for future in as_completed(futures):
                yield future.result()
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
