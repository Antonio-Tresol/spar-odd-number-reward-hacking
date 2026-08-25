"""Collect Odd Number rollouts and write them to JSONL, one line per rollout.

Observability contract (AGENTS.md): every rollout is appended the moment it
returns, so a kill at any point loses at most one in-flight call. Re-running the
same command skips rollouts already present in the output file, keyed by
(variant, index) — so `--n 20` after `--n 5` collects only the missing 15.

This module *collects*; it does not judge. Parsing a number out of a response is
where measurement bugs hide, so that lives in `grades.py` and runs as a
separate pass over the raw JSONL. Raw text is never discarded.

Two boundaries are deliberately outside this module. Retries belong to the SDK
(`client.py` explains why there is exactly one retry layer), and translating the
SDK's types into this project's belongs to `completions.py`. Nothing here touches a
`ChatResult`; it works with `Completion` and lets a vendor shape change fail
loudly at the boundary instead of quietly here.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path
from time import monotonic
from typing import Any, NotRequired, TextIO, TypedDict

from openrouter import OpenRouter

from odd_number.candidates import REASONING_ENABLED, Candidate, build_routing_body
from odd_number.client import METADATA_ENABLED
from odd_number.completions import (
    READABLE_REASONING,
    Completion,
    Routing,
    TokenUsage,
    parse_completion,
)
from odd_number.environment import Variant, build_prompt
from odd_number.sampling import DEFAULT_SAMPLING, SamplingParams


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

    variant: NotRequired[str]
    condition: NotRequired[str]
    index: NotRequired[int]
    model: NotRequired[str]
    snapshot: NotRequired[str]
    provider: NotRequired[str]
    sampling: NotRequired[dict[str, Any]]
    seed: NotRequired[int]
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

    variant: str
    condition: str
    index: int
    model: str
    snapshot: str
    provider: str
    reasoning_effort: str | None
    sampling: dict[str, Any]
    seed: int
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

    Passing `(client, variant, index, candidate, sampling)` positionally through
    the call chain is how argument-order bugs get in — `variant` and `candidate`
    are both objects nobody would notice transposed at a call site.
    """

    candidate: Candidate
    variant: Variant
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


def load_completed_keys(out_path: Path) -> set[tuple[str, int]]:
    """(variant, index) pairs already collected, so a re-run resumes.

    Errored rollouts are deliberately absent, so a re-run retries them.
    """
    return {
        (record["variant"], record["index"])
        for record in read_rollouts(out_path)
        if record.get("error") is None
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
    client: OpenRouter, candidate: Candidate, prompt: str, seed: int, sampling: SamplingParams
) -> Completion:
    """One chat completion against a pinned endpoint.

    The dated `snapshot` goes out as the model, not the alias, and `build_routing_body()`
    forbids fallbacks — so if the pinned endpoint is gone this raises rather
    than quietly returning a different provider's tokens. `METADATA_ENABLED` is
    what makes the response say who served it. The SDK retries transient
    failures internally.
    """
    extra: dict[str, Any] = {}
    if candidate.effort is not None:
        extra["reasoning_effort"] = candidate.effort
    result = client.chat.send(
        model=candidate.snapshot,
        messages=[{"role": "user", "content": prompt}],
        seed=seed,
        stream=False,
        reasoning=REASONING_ENABLED,
        provider=build_routing_body(candidate.provider),
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
    """Assemble the record. A failed rollout records blanks, never a fake answer."""
    done = completion or Completion(gen_id="", response="", reasoning="")
    return Rollout(
        variant=request.variant.label,
        condition=request.variant.condition,
        index=request.index,
        model=request.candidate.slug,
        snapshot=request.candidate.snapshot,
        provider=request.candidate.provider,
        reasoning_effort=request.candidate.effort,
        sampling=request.sampling.as_record(),
        seed=seed,
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
    prompt = build_prompt(request.variant)
    seed = derive_seed(request.variant.label, request.index)
    started = monotonic()
    completion: Completion | None = None
    error: str | None = None
    try:
        if client is None:
            completion = build_mock_completion(prompt, seed)
        else:
            completion = request_completion(
                client, request.candidate, prompt, seed, request.sampling
            )
    except Exception as exc:  # noqa: BLE001 — recorded, not swallowed
        error = f"{type(exc).__name__}: {exc}"
    return build_rollout(request, prompt, seed, completion, error, round(monotonic() - started, 3))


def append_rollout(handle: TextIO, rollout: Rollout) -> None:
    """Write one rollout and flush, so a kill loses at most the in-flight call."""
    handle.write(json.dumps(asdict(rollout), ensure_ascii=False) + "\n")
    handle.flush()
