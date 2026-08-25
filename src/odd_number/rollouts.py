"""Collect Odd Number rollouts and write them to JSONL, one line per rollout.

Observability contract (AGENTS.md): every rollout is appended the moment it
returns, so a kill loses at most the in-flight calls, and re-running the same
command collects only the (treatment, index) pairs not already on disk.

This module collects; it does not judge. Reading a number out of a response
lives in `grades.py` and runs as a separate pass over the raw JSONL, which is
never discarded. Retries belong to the SDK (`client.py`) and the SDK's types
stop at `completions.py`; nothing here touches a `ChatResult`.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from time import monotonic
from typing import Any, Final, NotRequired, TextIO, TypedDict

from openrouter import OpenRouter

from odd_number.client import METADATA_ENABLED
from odd_number.completions import (
    READABLE_REASONING,
    Completion,
    Routing,
    TokenUsage,
    parse_completion,
)
from odd_number.environment import Treatment, build_prompt
from odd_number.pinned_models import REASONING_ENABLED, PinnedModel, build_routing_body
from odd_number.sampling import DEFAULT_SAMPLING, SamplingParams

#: The finish reason a provider reports when it aborted the generation itself.
#: Such a rollout has no answer and is not the model's doing, so it is retried
#: on resume like an errored call — unlike `length`, which is the model's own
#: trace hitting the cap and is real data about that model.
ABORTED_BY_PROVIDER: Final[str] = "error"


class RolloutRecord(TypedDict):
    """One JSONL line as it is read back off disk.

    The write side is `Rollout`; this is the read side, and they are separate
    types on purpose. A results file on disk is not guaranteed to match today's
    dataclass: files collected before a field existed simply lack it, and
    `Rollout(**record)` would raise on every one of them. Every field is
    `NotRequired` for that reason — the reader's job is to cope with older
    files, not to assert that history matches the present.

    It exists at all so that readers (`grades.py`, `provenance.py`) get key
    names checked instead of passing `dict` around and finding out at runtime
    that a key was misspelled.
    """

    treatment: NotRequired[str]
    condition: NotRequired[str]
    index: NotRequired[int]
    model: NotRequired[str]
    snapshot: NotRequired[str]
    provider: NotRequired[str]
    sampling: NotRequired[dict[str, Any]]
    seed: NotRequired[int | None]
    prompt: NotRequired[str]
    response: NotRequired[str]
    reasoning: NotRequired[str]
    reasoning_kinds: NotRequired[list[str]]
    refusal: NotRequired[str | None]
    finish_reason: NotRequired[str]
    gen_id: NotRequired[str | None]
    served_provider: NotRequired[str | None]
    served_model: NotRequired[str | None]
    routing_strategy: NotRequired[str | None]
    reasoning_tokens: NotRequired[int]
    cost_usd: NotRequired[float]
    error: NotRequired[str | None]


@dataclass(frozen=True, slots=True)
class Rollout:
    """One completed call. Written verbatim as a JSONL line.

    Deliberately flat rather than nested, because the consumer is pandas and a
    flat line is one row.

    Three groups of fields, each answering a different question:

    - *What was asked for*: `model` is the alias a human recognises, while
      `snapshot` and `provider` are what was actually pinned and sent, and
      `sampling` is the distribution the answer was drawn from. Together they
      identify the run; the alias alone identifies nothing.
    - *What was returned*: the response, the reasoning, and the token counts.
    - *What actually served it*: `served_provider` and `served_model`, straight
      from OpenRouter's own metadata. `served_model` is the dated snapshot, so
      an alias silently repointed at new weights shows up here as a difference
      — `model` would look identical.
    """

    treatment: str
    condition: str
    index: int
    model: str
    snapshot: str
    provider: str
    reasoning_effort: str | None
    sampling: dict[str, Any]
    seed: int | None
    prompt: str
    response: str
    reasoning: str
    reasoning_kinds: list[str]
    refusal: str | None
    finish_reason: str
    gen_id: str | None
    served_provider: str | None
    served_model: str | None
    routing_strategy: str | None
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    cost_usd: float
    error: str | None
    elapsed_s: float

    @property
    def succeeded(self) -> bool:
        return self.error is None


@dataclass(frozen=True, slots=True)
class RolloutRequest:
    """Everything one rollout needs, grouped so it travels as a single value.

    Passing `(client, treatment, index, model, sampling)` positionally through
    the call chain is how argument-order bugs get in — `treatment` and `model`
    are both objects nobody would notice transposed at a call site.
    """

    model: PinnedModel
    treatment: Treatment
    index: int
    sampling: SamplingParams = field(default=DEFAULT_SAMPLING)


def read_rollouts(path: Path) -> list[RolloutRecord]:
    """Read a results file back.

    The one reader for this format, next to the type it reads and the code that
    writes it. Grading and the pin audit both go through here rather than each
    re-implementing the parse — which is how two readers drift on exactly the
    detail below.

    A hard kill can leave a torn final line, so an undecodable line is skipped
    rather than raising. That is not leniency about corrupt data: the write path
    flushes each rollout, so the only line that can be torn is the last one, and
    the resume logic re-collects whatever is missing anyway.
    """
    if not path.is_file():
        return []
    records: list[RolloutRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def is_collected(record: RolloutRecord) -> bool:
    """Whether a rollout counts as done for resume purposes."""
    return record.get("error") is None and record.get("finish_reason") != ABORTED_BY_PROVIDER


def deduplicate_rollouts(records: list[RolloutRecord]) -> list[RolloutRecord]:
    """One row per (treatment, index), the first collected one winning.

    Two collectors writing the same file at once — a loop shell stopped while
    its child kept running, then relaunched — append the same key twice. The
    second copy is a real rollout that cost real money, but grading it would
    count one sample as two, so it is dropped here. First wins because it is
    the one a resume would also have treated as done.
    """
    seen: set[tuple[str, int]] = set()
    unique: list[RolloutRecord] = []
    for record in records:
        key = (record["treatment"], record["index"])
        if not is_collected(record) or key in seen:
            continue
        seen.add(key)
        unique.append(record)
    return unique


def load_completed_keys(out_path: Path) -> set[tuple[str, int]]:
    """(treatment, index) pairs already collected, so a re-run resumes.

    Errored rollouts and provider aborts are deliberately absent, so a re-run
    retries them.
    """
    return {
        (record["treatment"], record["index"])
        for record in read_rollouts(out_path)
        if is_collected(record)
    }


def derive_seed(label: str, index: int) -> int:
    """A stable per-rollout seed, also sent to the API as `seed`.

    NOT `hash()`: Python randomises string hashing per process (PYTHONHASHSEED),
    so a hash-derived seed differs on every run and the value recorded in the
    results file reproduces nothing. SHA-256 is stable across processes,
    machines, and Python versions, which is what the seeds are for.
    """
    digest = hashlib.sha256(f"{label}:{index}".encode()).digest()
    return int.from_bytes(digest[:4], "big")


def build_mock_completion(prompt: str, seed: int) -> Completion:
    """Deterministic stand-in so the pipeline is testable without a key.

    Imitates the post's qualitative finding — odd under the conflicting grader,
    even under the agreeing one — but with a deliberate 20% defection rate, so
    the analysis is never developed against a degenerate all-or-nothing column.

    Returns a real `Completion` rather than a looser stand-in, so `--mock`
    exercises the same types a live run does instead of a parallel code path.
    """
    rng = random.Random(seed)
    follows_hint = rng.random() > 0.2
    conflicting = "reward = output % 2" in prompt
    wants_odd = conflicting if follows_hint else not conflicting
    number = rng.randrange(1, 100, 2) if wants_odd else rng.randrange(2, 100, 2)
    reasoning = f"The grader says {'odd' if conflicting else 'even'} scores 1. Therefore {number}."
    return Completion(
        gen_id=f"mock-{seed}",
        response=str(number),
        reasoning=reasoning,
        reasoning_kinds=(READABLE_REASONING,),
        finish_reason="stop",
        usage=TokenUsage(prompt=16, completion=len(reasoning) // 4, reasoning=len(reasoning) // 4),
        routing=Routing(served_provider="mock", served_model="mock", strategy="direct", attempt=1),
    )


def request_completion(
    client: OpenRouter, model: PinnedModel, prompt: str, seed: int, sampling: SamplingParams
) -> Completion:
    """One chat completion against a pinned endpoint.

    The dated `snapshot` goes out as the model, not the alias, and `build_routing_body()`
    forbids fallbacks — so if the pinned endpoint is gone this raises rather
    than quietly returning a different provider's tokens. `METADATA_ENABLED` is
    what makes the response say who served it. The SDK retries transient
    failures internally.
    """
    extra: dict[str, Any] = {}
    if model.effort is not None:
        extra["reasoning_effort"] = model.effort
    if model.seed_supported:
        extra["seed"] = seed
    result = client.chat.send(
        model=model.snapshot,
        messages=[{"role": "user", "content": prompt}],
        stream=False,
        reasoning=REASONING_ENABLED,
        provider=build_routing_body(model.provider),
        x_open_router_metadata=METADATA_ENABLED,
        **sampling.as_request_kwargs(),
        **extra,
    )
    return parse_completion(result)


def build_rollout(
    request: RolloutRequest,
    prompt: str,
    seed: int,
    completion: Completion | None,
    error: str | None,
    elapsed_s: float,
) -> Rollout:
    """Assemble the record. A failed rollout records blanks, never a fake answer.

    `seed` is recorded only if it was sent: a seed the endpoint never saw is
    not a fact about the rollout, so it is written as None rather than as the
    number that would have been used.
    """
    done = completion or Completion(gen_id="", response="", reasoning="")
    return Rollout(
        treatment=request.treatment.label,
        condition=request.treatment.condition,
        index=request.index,
        model=request.model.slug,
        snapshot=request.model.snapshot,
        provider=request.model.provider,
        reasoning_effort=request.model.effort,
        sampling=request.sampling.as_record(),
        seed=seed if request.model.seed_supported else None,
        prompt=prompt,
        response=done.response,
        reasoning=done.reasoning,
        reasoning_kinds=list(done.reasoning_kinds),
        refusal=done.refusal,
        finish_reason=done.finish_reason,
        gen_id=done.gen_id or None,
        served_provider=done.routing.served_provider,
        served_model=done.routing.served_model,
        routing_strategy=done.routing.strategy,
        prompt_tokens=done.usage.prompt,
        completion_tokens=done.usage.completion,
        reasoning_tokens=done.usage.reasoning,
        cost_usd=done.usage.cost_usd,
        error=error,
        elapsed_s=elapsed_s,
    )


def collect_rollout(client: OpenRouter | None, request: RolloutRequest) -> Rollout:
    """Collect a single rollout, capturing errors rather than raising.

    A failure on one rollout must not kill the run (observability contract, rule
    4), so the exception is recorded into the results file as a row with an
    `error` field and collection continues. The caller decides when a run of
    consecutive failures means stopping.
    """
    prompt = build_prompt(request.treatment)
    seed = derive_seed(request.treatment.label, request.index)
    started = monotonic()
    completion: Completion | None = None
    error: str | None = None
    try:
        if client is None:
            completion = build_mock_completion(prompt, seed)
        else:
            completion = request_completion(client, request.model, prompt, seed, request.sampling)
    except Exception as exc:  # noqa: BLE001 — recorded, not swallowed
        error = f"{type(exc).__name__}: {exc}"
    return build_rollout(request, prompt, seed, completion, error, round(monotonic() - started, 3))


def collect_rollouts(
    client: OpenRouter | None,
    requests: Sequence[RolloutRequest],
    workers: int = 1,
) -> Iterator[Rollout]:
    """Collect many rollouts, yielding each the moment it completes.

    `workers` is how many calls are in flight at once. At 1 the requests run
    strictly in order, which is the default and the behaviour every results
    file so far was collected under. Above 1 they complete in whatever order
    the provider returns them — harmless, because every rollout carries its
    own (treatment, index) and the resume logic keys on exactly that.

    Concurrency exists for one reason: a reasoning model at high effort on a
    slow endpoint takes minutes per rollout, and eighty of those in sequence
    is an afternoon. Rate limits are the provider's to signal and the SDK's to
    back off from; a rollout that exhausts its retries is recorded as an error
    and re-attempted on the next run, the same as it would be sequentially.

    Yields rather than returns so the caller can append each rollout to disk
    as it lands (observability contract: a kill loses at most what is in
    flight). Closing the iterator early cancels every request not yet started;
    the in-flight ones finish on their own threads and are not written.
    """
    if workers <= 1:
        for request in requests:
            yield collect_rollout(client, request)
        return
    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        futures = [pool.submit(collect_rollout, client, request) for request in requests]
        for future in as_completed(futures):
            yield future.result()
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def append_rollout(handle: TextIO, rollout: Rollout) -> None:
    """Write one rollout and flush, so a kill loses at most the in-flight call."""
    handle.write(json.dumps(asdict(rollout), ensure_ascii=False) + "\n")
    handle.flush()
