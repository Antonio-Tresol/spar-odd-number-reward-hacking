"""Collect Odd Number rollouts and write them to JSONL, one line per rollout.

Observability contract (AGENTS.md): every rollout is appended the moment it
returns, so a kill at any point loses at most one in-flight call. Re-running the
same command skips rollouts already present in the output file, keyed by
(variant, index) — so `--n 20` after `--n 5` collects only the missing 15.

This module *collects*; it does not judge. Parsing a number out of a response is
where measurement bugs hide, so that lives in `grading.py` and runs as a
separate pass over the raw JSONL. Raw text is never discarded.

Retries are the SDK's job — see `client.py` for why there is exactly one retry
layer.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from time import monotonic
from typing import Any

from openrouter import OpenRouter

from .env import Variant, build_prompt

#: Reasoning we can actually read, as opposed to a provider-side summary or an
#: encrypted blob. The distinction is load-bearing: the forensics protocol's
#: first step is reading the CoT, and a *summary* is not the CoT. Treating one
#: as the other would quietly turn "what the model reasoned" into "what the
#: provider chose to tell us about it".
READABLE_REASONING = "reasoning.text"


@dataclass(frozen=True, slots=True)
class Rollout:
    """One completed call. Written verbatim as a JSONL line."""

    variant: str
    condition: str
    index: int
    model: str
    seed: int
    prompt: str
    response: str
    reasoning: str
    reasoning_kinds: list[str]
    refusal: str | None
    finish_reason: str
    usage: dict[str, Any]
    error: str | None
    elapsed_s: float


def load_dotenv(root: Path) -> None:
    """Read a gitignored .env if present. Deliberately minimal: KEY=value only."""
    path = root / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def done_keys(out_path: Path) -> set[tuple[str, int]]:
    """(variant, index) pairs already collected, so a re-run resumes."""
    if not out_path.is_file():
        return set()
    done: set[tuple[str, int]] = set()
    for line in out_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue  # a torn final line from a hard kill; it will be re-run
        if record.get("error") is None:
            done.add((record["variant"], record["index"]))
    return done


def seed_for(label: str, index: int) -> int:
    """A stable per-rollout seed, also sent to the API as `seed`.

    NOT `hash()`: Python randomises string hashing per process (PYTHONHASHSEED),
    so a hash-derived seed differs on every run and the value recorded in the
    results file reproduces nothing. SHA-256 is stable across processes,
    machines, and Python versions, which is what the seeds are for.
    """
    digest = hashlib.sha256(f"{label}:{index}".encode()).digest()
    return int.from_bytes(digest[:4], "big")


def mock_response(prompt: str, seed: int) -> tuple[str, str]:
    """Deterministic stand-in so the pipeline is testable without a key.

    Imitates the post's qualitative finding — odd under the conflicting grader,
    even under the agreeing one — but with a deliberate 20% defection rate, so
    the analysis is never developed against a degenerate all-or-nothing column.
    """
    rng = random.Random(seed)
    follows_hint = rng.random() > 0.2
    conflicting = "reward = output % 2" in prompt
    wants_odd = conflicting if follows_hint else not conflicting
    number = rng.randrange(1, 100, 2) if wants_odd else rng.randrange(2, 100, 2)
    reasoning = f"The grader says {'odd' if conflicting else 'even'} scores 1. "
    return str(number), reasoning + f"Therefore {number}."


def reasoning_kinds(message: Any) -> list[str]:
    """Which kinds of reasoning the provider returned, e.g. `reasoning.text`.

    Empty when the provider returned none. See READABLE_REASONING for why the
    kind is recorded rather than assumed.
    """
    details = getattr(message, "reasoning_details", None) or []
    kinds: list[str] = []
    for detail in details:
        kind = getattr(detail, "type", None)
        if kind is not None:
            kinds.append(str(kind))
    return kinds


def extract(result: Any) -> dict[str, Any]:
    """Pull the fields worth keeping out of a ChatResult."""
    choice = result.choices[0]
    message = choice.message
    return {
        "response": getattr(message, "content", None) or "",
        "reasoning": getattr(message, "reasoning", None) or "",
        "reasoning_kinds": reasoning_kinds(message),
        "refusal": getattr(message, "refusal", None),
        "finish_reason": getattr(choice, "finish_reason", None) or "",
        "usage": result.usage.model_dump() if getattr(result, "usage", None) else {},
    }


def call_model(client: OpenRouter, model: str, prompt: str, seed: int) -> dict[str, Any]:
    """One chat completion. The SDK retries transient failures internally."""
    result = client.chat.send(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=1.0,
        seed=seed,
        stream=False,
    )
    return extract(result)


def blank_fields() -> dict[str, Any]:
    """The response fields, unset — what a failed rollout records."""
    return {
        "response": "",
        "reasoning": "",
        "reasoning_kinds": [],
        "refusal": None,
        "finish_reason": "",
        "usage": {},
    }


def run_one(client: OpenRouter | None, variant: Variant, index: int, model: str) -> Rollout:
    """Collect a single rollout, capturing errors rather than raising."""
    prompt = build_prompt(variant)
    seed = seed_for(variant.label, index)
    started = monotonic()
    fields = blank_fields()
    error: str | None = None
    try:
        if client is None:
            response, reasoning = mock_response(prompt, seed)
            fields |= {
                "response": response,
                "reasoning": reasoning,
                "reasoning_kinds": [READABLE_REASONING],
                "finish_reason": "stop",
            }
        else:
            fields = call_model(client, model, prompt, seed)
    except Exception as exc:  # noqa: BLE001 — recorded, not swallowed
        error = f"{type(exc).__name__}: {exc}"
    return Rollout(
        variant=variant.label,
        condition=variant.condition,
        index=index,
        model=model,
        seed=seed,
        prompt=prompt,
        error=error,
        elapsed_s=round(monotonic() - started, 3),
        **fields,
    )


def append_rollout(handle: Any, rollout: Rollout) -> None:
    """Write one rollout and flush, so a kill loses at most the in-flight call."""
    handle.write(json.dumps(asdict(rollout), ensure_ascii=False) + "\n")
    handle.flush()
