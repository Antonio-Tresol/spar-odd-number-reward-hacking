"""Tests for the collection runner: retry policy and resume bookkeeping.

The retry tests matter more than they look. A retry loop that retries a 401
turns one wrong key into six wrong keys and a long wait; a loop that *doesn't*
retry a 429 throws away a paid run on a rate limit. Both failures are silent
under happy-path testing, so both are asserted here directly.

No test sleeps: `time.sleep` is monkeypatched and the requested delays are
recorded, which also lets the backoff bounds be asserted rather than eyeballed.

Run:  uv run pytest tests/test_collect.py
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from odd_number.collect import done_keys, seed_for
from odd_number.retry import (
    RETRYABLE_STATUS,
    RetryPolicy,
    TransientError,
    classify_failure,
    with_retries,
)


def status_error(code: int, headers: dict[str, str] | None = None) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://example.invalid")
    response = httpx.Response(code, headers=headers or {}, request=request)
    return httpx.HTTPStatusError(f"HTTP {code}", request=request, response=response)


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Record requested sleeps instead of performing them."""
    recorded: list[float] = []
    monkeypatch.setattr("odd_number.retry.time.sleep", recorded.append)
    return recorded


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


# --- backoff -------------------------------------------------------------


def test_server_retry_after_overrides_computed_backoff() -> None:
    assert RetryPolicy().delay_for(attempt=0, retry_after=12.0) == 12.0


def test_retry_after_is_still_capped() -> None:
    """Obey the server, but never sleep past max_delay on one attempt."""
    policy = RetryPolicy(max_delay=30.0)
    assert policy.delay_for(attempt=0, retry_after=9999.0) == 30.0


def test_full_jitter_stays_within_the_exponential_cap() -> None:
    policy = RetryPolicy(base_delay=1.0, max_delay=60.0)
    for attempt in range(6):
        cap = min(1.0 * (2**attempt), 60.0)
        for _ in range(50):
            assert 0.0 <= policy.delay_for(attempt) <= cap


# --- the retry loop ------------------------------------------------------


def test_succeeds_after_transient_failures(no_sleep: list[float]) -> None:
    calls = {"n": 0}

    def flaky() -> dict[str, object]:
        calls["n"] += 1
        if calls["n"] < 3:
            raise status_error(503)
        return {"ok": True}

    assert with_retries(flaky, RetryPolicy(), "label") == {"ok": True}
    assert calls["n"] == 3
    assert len(no_sleep) == 2  # slept between attempts, not after the success


def test_permanent_error_is_raised_immediately_without_sleeping(
    no_sleep: list[float],
) -> None:
    calls = {"n": 0}

    def unauthorized() -> dict[str, object]:
        calls["n"] += 1
        raise status_error(401)

    with pytest.raises(httpx.HTTPStatusError):
        with_retries(unauthorized, RetryPolicy(), "label")
    assert calls["n"] == 1
    assert no_sleep == []


def test_exhausting_attempts_raises_and_uses_the_whole_budget(
    no_sleep: list[float],
) -> None:
    calls = {"n": 0}

    def always_429() -> dict[str, object]:
        calls["n"] += 1
        raise status_error(429)

    policy = RetryPolicy(max_attempts=4)
    with pytest.raises(RuntimeError, match="exhausted 4 attempts"):
        with_retries(always_429, policy, "label")
    assert calls["n"] == 4
    assert len(no_sleep) == 3  # no sleep after the final failure


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
        json.dumps({"variant": "agree-grader", "index": 0, "error": None}) + "\n{\"var",
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
