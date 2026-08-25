"""Tests for collection: resume bookkeeping, seeds, and response extraction.

There are no retry tests any more, and that is the point: retries belong to the
OpenRouter SDK's RetryConfig, which already does backoff-with-jitter and honours
Retry-After / retry-after-ms headers. Re-testing a vendor's retry loop tests the
vendor. What is tested here is what this project actually decides.

The extraction tests carry the weight. `reasoning_kinds` is the difference
between reading a model's chain of thought and reading a provider's *summary*
of it — a distinction the forensics protocol depends on and one that a naive
`message.reasoning` read would silently lose.

Run:  uv run pytest tests/test_collect.py
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from odd_number.collect import (
    READABLE_REASONING,
    done_keys,
    extract,
    reasoning_kinds,
    seed_for,
)


def fake_result(
    content: str = "42",
    reasoning: str = "thinking",
    details: list[object] | None = None,
    refusal: str | None = None,
    finish_reason: str = "stop",
) -> SimpleNamespace:
    """A stand-in shaped like the SDK's ChatResult, duck-typed."""
    message = SimpleNamespace(
        content=content,
        reasoning=reasoning,
        reasoning_details=details,
        refusal=refusal,
    )
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], usage=None)


# --- reasoning provenance ------------------------------------------------


def test_readable_reasoning_is_recognised() -> None:
    result = fake_result(details=[SimpleNamespace(type="reasoning.text")])
    assert extract(result)["reasoning_kinds"] == [READABLE_REASONING]


def test_a_summary_is_not_recorded_as_readable_reasoning() -> None:
    """A provider-side summary is not the CoT, and must not pass as one."""
    result = fake_result(details=[SimpleNamespace(type="reasoning.summary")])
    kinds = extract(result)["reasoning_kinds"]
    assert kinds == ["reasoning.summary"]
    assert READABLE_REASONING not in kinds


def test_encrypted_reasoning_is_recorded_as_such() -> None:
    result = fake_result(details=[SimpleNamespace(type="reasoning.encrypted")])
    assert extract(result)["reasoning_kinds"] == ["reasoning.encrypted"]


def test_missing_reasoning_details_gives_an_empty_list_not_a_crash() -> None:
    """Most non-reasoning models return nothing here."""
    assert reasoning_kinds(SimpleNamespace(reasoning_details=None)) == []
    assert reasoning_kinds(SimpleNamespace()) == []


# --- extraction ----------------------------------------------------------


def test_extract_pulls_the_fields_we_keep() -> None:
    fields = extract(fake_result(content="42", reasoning="because"))
    assert fields["response"] == "42"
    assert fields["reasoning"] == "because"
    assert fields["finish_reason"] == "stop"
    assert fields["refusal"] is None


def test_null_content_becomes_empty_string_not_none() -> None:
    """A refusal can leave content null; downstream grading expects a string."""
    fields = extract(fake_result(content=None, refusal="I can't help with that"))
    assert fields["response"] == ""
    assert fields["refusal"] == "I can't help with that"


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
