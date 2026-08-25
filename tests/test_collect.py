"""Tests for collection: retry policy, resume bookkeeping, and seeds.

What is tested here is *policy*, not tenacity. A retry loop that retries a 401
turns one wrong key into six wrong keys and a long wait; a loop that *doesn't*
retry a 429 throws away a paid run on a rate limit. Both failures are silent
under happy-path testing, so the classification and the backoff choice are
asserted directly. Attempt counting and exhaustion semantics belong to tenacity
and are not re-tested.

No test sleeps: tenacity's `sleep` is injected via `retry_with(sleep=...)`,
which records the requested delays and lets the backoff be asserted rather than
eyeballed.

Run:  uv run pytest tests/test_collect.py
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from tenacity import stop_after_attempt

from odd_number.collect import done_keys, seed_for
from odd_number.retry import (
    MAX_DELAY,
    RETRYABLE_STATUS,
    TransientError,
    api_retry,
    as_transient,
    classify_failure,
)


def status_error(code: int, headers: dict[str, str] | None = None) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://example.invalid")
    response = httpx.Response(code, headers=headers or {}, request=request)
    return httpx.HTTPStatusError(f"HTTP {code}", request=request, response=response)


def make_flaky(failures: int, exc_factory=lambda: status_error(503)):
    """A decorated callable that fails `failures` times, then succeeds.

    Decorated exactly as the real `call_model` is, so the test exercises the
    same stack rather than a lookalike.
    """
    calls = {"n": 0}

    @api_retry
    @as_transient
    def flaky() -> dict[str, object]:
        calls["n"] += 1
        if calls["n"] <= failures:
            raise exc_factory()
        return {"ok": calls["n"]}

    return flaky, calls


# --- classification ------------------------------------------------------


@pytest.mark.parametrize("code", sorted(RETRYABLE_STATUS))
def test_transient_statuses_are_retryable(code: int) -> None:
    assert isinstance(classify_failure(status_error(code)), TransientError)


@pytest.mark.parametrize("code", [400, 401, 403, 404, 422])
def test_permanent_statuses_are_not_retryable(code: int) -> None:
    """A bad key or a bad model name fails identically forever — don't spin."""
    assert not isinstance(classify_failure(status_error(code)), TransientError)


def test_timeouts_and_transport_errors_are_retryable() -> None:
    assert isinstance(classify_failure(httpx.ReadTimeout("slow")), TransientError)
    assert isinstance(classify_failure(httpx.ConnectError("refused")), TransientError)


def test_retry_after_is_parsed_from_the_header() -> None:
    converted = classify_failure(status_error(429, {"retry-after": "17"}))
    assert isinstance(converted, TransientError)
    assert converted.retry_after == 17.0


def test_http_date_retry_after_falls_back_to_computed_backoff() -> None:
    """We parse seconds only; a date form must not crash, just fall through."""
    converted = classify_failure(
        status_error(429, {"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"})
    )
    assert isinstance(converted, TransientError)
    assert converted.retry_after is None


def test_classify_returns_the_same_object_for_permanent_errors() -> None:
    """`as_transient` uses identity to decide whether to re-raise untouched."""
    exc = status_error(401)
    assert classify_failure(exc) is exc


# --- backoff policy ------------------------------------------------------


def test_server_retry_after_overrides_computed_backoff() -> None:
    slept: list[float] = []
    flaky, _ = make_flaky(2, lambda: status_error(429, {"retry-after": "7"}))
    flaky.retry_with(sleep=slept.append)()
    assert slept == [7.0, 7.0]


def test_retry_after_is_capped_at_max_delay() -> None:
    """Obey the server, but never sleep past MAX_DELAY on one attempt."""
    slept: list[float] = []
    flaky, _ = make_flaky(1, lambda: status_error(429, {"retry-after": "9999"}))
    flaky.retry_with(sleep=slept.append)()
    assert slept == [MAX_DELAY]


def test_backoff_without_retry_after_is_jittered_and_bounded() -> None:
    """Full jitter: every delay in [0, cap], and not a constant.

    A fixed backoff would make simultaneously rate-limited callers retry in
    lockstep and re-trigger the limit, so the randomness is the point.
    """
    seen: list[float] = []
    for _ in range(30):
        slept: list[float] = []
        flaky, _ = make_flaky(3)  # 503, no retry-after header
        flaky.retry_with(sleep=slept.append)()
        assert len(slept) == 3
        for attempt, delay in enumerate(slept):
            assert 0.0 <= delay <= min(1.0 * (2**attempt), MAX_DELAY)
        seen.extend(slept)
    assert len(set(seen)) > 1, "delays are constant — jitter is not being applied"


# --- the retry loop (integration with tenacity) --------------------------


def test_succeeds_after_transient_failures() -> None:
    slept: list[float] = []
    flaky, calls = make_flaky(2)
    assert flaky.retry_with(sleep=slept.append)() == {"ok": 3}
    assert calls["n"] == 3
    assert len(slept) == 2  # slept between attempts, not after the success


def test_permanent_error_is_raised_immediately_without_sleeping() -> None:
    slept: list[float] = []
    flaky, calls = make_flaky(99, lambda: status_error(401))
    with pytest.raises(httpx.HTTPStatusError):
        flaky.retry_with(sleep=slept.append)()
    assert calls["n"] == 1
    assert slept == []


def test_exhausting_attempts_reraises_the_underlying_error() -> None:
    """reraise=True: the caller sees the real failure, not a RetryError wrapper."""
    slept: list[float] = []
    flaky, calls = make_flaky(99, lambda: status_error(429))
    with pytest.raises(TransientError, match="HTTP 429"):
        flaky.retry_with(stop=stop_after_attempt(4), sleep=slept.append)()
    assert calls["n"] == 4
    assert len(slept) == 3  # no sleep after the final failure


# --- resume bookkeeping --------------------------------------------------


def test_done_keys_skips_errored_rollouts(tmp_path: Path) -> None:
    """An errored rollout must be re-attempted, not counted as collected."""
    path = tmp_path / "r.jsonl"
    path.write_text(
        json.dumps({"variant": "conflict-grader", "index": 0, "error": None})
        + "\n"
        + json.dumps({"variant": "conflict-grader", "index": 1, "error": "boom"})
        + "\n",
        encoding="utf-8",
    )
    assert done_keys(path) == {("conflict-grader", 0)}


def test_done_keys_tolerates_a_torn_final_line(tmp_path: Path) -> None:
    """A hard kill mid-write must not make the whole results file unreadable."""
    path = tmp_path / "r.jsonl"
    path.write_text(
        json.dumps({"variant": "agree-grader", "index": 0, "error": None}) + '\n{"var',
        encoding="utf-8",
    )
    assert done_keys(path) == {("agree-grader", 0)}


def test_done_keys_on_a_missing_file_is_empty(tmp_path: Path) -> None:
    assert done_keys(tmp_path / "nope.jsonl") == set()


# --- seeds ---------------------------------------------------------------


def test_seed_is_pinned_to_a_literal_value() -> None:
    """Pinned, not just self-consistent.

    An in-process "call it twice, get the same answer" test passes happily for
    `hash()` too — the randomisation is per *process*, not per call. Only a
    hardcoded expected value catches a seed that silently changes between runs.
    """
    assert seed_for("conflict-grader", 0) == 2_450_989_572
    assert seed_for("agree-grader", 0) == 3_137_547_086


def test_seed_varies_with_both_label_and_index() -> None:
    assert seed_for("conflict-grader", 0) != seed_for("conflict-grader", 1)
    assert seed_for("conflict-grader", 0) != seed_for("agree-grader", 0)
