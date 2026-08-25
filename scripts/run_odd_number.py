#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["httpx>=0.27"]
# ///
"""Collect Odd Number rollouts and write them to JSONL, one line per rollout.

Observability contract (AGENTS.md): every rollout is appended the moment it
returns, so a kill at any point loses at most one in-flight call. Re-running the
same command skips rollouts already present in the output file, keyed by
(variant, index) — so `--n 20` after `--n 5` collects only the missing 15.

This script *collects*; it does not judge. Parsing a number out of a response is
where measurement bugs hide, so that lives in grade_odd_number.py and is graded
in a separate pass over the raw JSONL. Raw text is never discarded.

Provider: OpenRouter, so one key reaches every model worth comparing. Set
OPENROUTER_API_KEY in a gitignored .env or the environment.

Run:
    uv run scripts/run_odd_number.py --mock --n 5          # no key needed
    uv run scripts/run_odd_number.py --model deepseek/deepseek-r1 --n 40
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

from odd_number_env import Variant, baseline_pair, build_prompt  # noqa: E402

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


def call_model(client: httpx.Client, model: str, prompt: str) -> dict[str, Any]:
    """One chat completion. Raises on HTTP error so the caller can fail fast."""
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
    """Collect a single rollout, capturing errors rather than raising."""
    prompt = build_prompt(variant)
    seed = abs(hash((variant.label, index))) % (2**31)
    started = time.monotonic()
    response = reasoning = finish = ""
    usage: dict[str, Any] = {}
    error: str | None = None
    try:
        if client is None:
            response, reasoning = mock_response(prompt, seed)
            finish = "stop"
        else:
            response, reasoning, finish, usage = extract(call_model(client, model, prompt))
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="deepseek/deepseek-r1")
    parser.add_argument("--n", type=int, default=40, help="rollouts per variant")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--mock", action="store_true", help="no API key needed")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parent.parent
    load_dotenv(root)

    if not args.mock and not os.environ.get("OPENROUTER_API_KEY"):
        print("OPENROUTER_API_KEY is not set. Put it in .env, or pass --mock.", file=sys.stderr)
        return 2

    slug = "mock" if args.mock else args.model.replace("/", "-")
    out_path = args.out or root / "results" / f"odd-number-{slug}.jsonl"
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

    client = None if args.mock else httpx.Client(timeout=TIMEOUT)
    failures = 0
    try:
        with out_path.open("a", encoding="utf-8") as handle:
            for position, (variant, index) in enumerate(todo, start=1):
                rollout = run_one(client, variant, index, args.model)
                handle.write(json.dumps(asdict(rollout), ensure_ascii=False) + "\n")
                handle.flush()
                if rollout.error:
                    failures += 1
                    print(f"  [{position}/{len(todo)}] {variant.label} ERROR {rollout.error}")
                    # Fail fast: a key or model-name problem fails identically
                    # every time, and burning the full budget to prove it is
                    # just an expensive way to read the same message.
                    if failures >= 3:
                        print("3 consecutive-ish failures; stopping.", file=sys.stderr)
                        return 1
                else:
                    failures = 0
                    print(f"  [{position}/{len(todo)}] {variant.label} -> {rollout.response[:40]!r}")
    finally:
        if client is not None:
            client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
