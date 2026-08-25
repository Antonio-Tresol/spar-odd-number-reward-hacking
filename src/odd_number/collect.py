"""Collect Odd Number rollouts and write them to JSONL, one line per rollout.

Observability contract (AGENTS.md): every rollout is appended the moment it
returns, so a kill at any point loses at most one in-flight call. Re-running the
same command skips rollouts already present in the output file, keyed by
(variant, index) — so `--n 20` after `--n 5` collects only the missing 15.

This module *collects*; it does not judge. Parsing a number out of a response is
where measurement bugs hide, so that lives in `grading.py` and runs as a
separate pass over the raw JSONL. Raw text is never discarded.

Provider: OpenRouter, so one key reaches every model worth comparing. Set
OPENROUTER_API_KEY in a gitignored .env or the environment.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

import httpx

from .env import Variant, build_prompt
from .retry import api_retry, as_transient

ENDPOINT: Final[str] = "https://openrouter.ai/api/v1/chat/completions"
TIMEOUT: Final[float] = 300.0


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
    """A stable per-rollout seed.

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


@api_retry
@as_transient
def call_model(client: httpx.Client, model: str, prompt: str) -> dict[str, Any]:
    """One chat completion, retrying transient failures.

    The decorators do the work: `as_transient` turns retryable httpx errors into
    TransientError, `api_retry` retries exactly that with jittered backoff.
    """
    response = client.post(
        ENDPOINT,
        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 1.0,
        },
    )
    response.raise_for_status()
    return response.json()


def extract(payload: dict[str, Any]) -> tuple[str, str, str, dict[str, Any]]:
    """Pull (response, reasoning, finish_reason, usage) out of an API payload."""
    choice = payload["choices"][0]
    message = choice.get("message", {})
    return (
        message.get("content") or "",
        message.get("reasoning") or "",
        choice.get("finish_reason") or "",
        payload.get("usage") or {},
    )


def run_one(client: httpx.Client | None, variant: Variant, index: int, model: str) -> Rollout:
    """Collect a single rollout, capturing errors rather than raising.

    `call_model` retries transient failures itself; only an exhausted retry
    budget or a permanent error (400/401/403) reaches the `error` field.
    """
    prompt = build_prompt(variant)
    seed = seed_for(variant.label, index)
    started = time.monotonic()
    response = reasoning = finish = ""
    usage: dict[str, Any] = {}
    error: str | None = None
    try:
        if client is None:
            response, reasoning = mock_response(prompt, seed)
            finish = "stop"
        else:
            payload = call_model(client, model, prompt)
            response, reasoning, finish, usage = extract(payload)
    except Exception as exc:  # noqa: BLE001 — recorded, not swallowed
        error = f"{type(exc).__name__}: {exc}"
    return Rollout(
        variant=variant.label,
        condition=variant.condition,
        index=index,
        model=model,
        seed=seed,
        prompt=prompt,
        response=response,
        reasoning=reasoning,
        finish_reason=finish,
        usage=usage,
        error=error,
        elapsed_s=round(time.monotonic() - started, 3),
    )


def append_rollout(handle: Any, rollout: Rollout) -> None:
    """Write one rollout and flush, so a kill loses at most the in-flight call."""
    handle.write(json.dumps(asdict(rollout), ensure_ascii=False) + "\n")
    handle.flush()
