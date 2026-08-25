"""Tests for the SDK boundary.

These carry the weight that `test_rollouts.py`'s extraction tests used to. Two
properties matter here, and they pull in opposite directions:

- A field the SDK *declares optional* (a null `content` on a refusal, absent
  `reasoning_details` on a non-reasoning model) must be handled quietly. Those
  are documented states.
- A field the SDK does not return in the shape we expect must raise. The code
  this replaces used `getattr(message, "content", None) or ""`, which turned a
  renamed field into an empty string — so a vendor change would have filled a
  results file with blank responses that grade exactly like refusals, and
  nothing would have failed.

`reasoning_kinds` is the other load-bearing case: it is the difference between
reading a model's chain of thought and reading a provider's *summary* of it, a
distinction the forensics protocol depends on.

Run:  uv run pytest tests/test_completions.py
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from odd_number.completions import (
    READABLE_REASONING,
    ResponseShapeError,
    Routing,
    parse_completion,
    parse_reasoning_kinds,
    parse_text,
)


def fake_endpoint(provider: str = "DeepInfra", model: str = "qwen/qwen3.6-27b-20260422"):
    return SimpleNamespace(provider=provider, model=model, selected=True)


def fake_result(
    content: str | None = "42",
    reasoning: str | None = "thinking",
    details: list[object] | None = None,
    refusal: str | None = None,
    finish_reason: str = "stop",
    endpoints: list[object] | None = None,
    metadata: object | None = ...,
    choices: list[object] | None = None,
) -> SimpleNamespace:
    """A stand-in shaped like the SDK's ChatResult."""
    message = SimpleNamespace(
        content=content, reasoning=reasoning, reasoning_details=details, refusal=refusal
    )
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    if metadata is ...:
        available = [fake_endpoint()] if endpoints is None else endpoints
        metadata = SimpleNamespace(
            endpoints=SimpleNamespace(available=available),
            strategy="direct",
            attempt=1,
        )
    return SimpleNamespace(
        id="gen-1",
        choices=[choice] if choices is None else choices,
        usage=None,
        openrouter_metadata=metadata,
    )


# --- reasoning provenance ------------------------------------------------


def test_readable_reasoning_is_recognised() -> None:
    result = fake_result(details=[SimpleNamespace(type="reasoning.text")])
    completion = parse_completion(result)
    assert completion.reasoning_kinds == (READABLE_REASONING,)
    assert completion.has_readable_reasoning


def test_a_summary_is_not_recorded_as_readable_reasoning() -> None:
    """A provider-side summary is not the CoT, and must not pass as one."""
    completion = parse_completion(fake_result(details=[SimpleNamespace(type="reasoning.summary")]))
    assert completion.reasoning_kinds == ("reasoning.summary",)
    assert not completion.has_readable_reasoning


def test_encrypted_reasoning_is_recorded_as_such() -> None:
    completion = parse_completion(
        fake_result(details=[SimpleNamespace(type="reasoning.encrypted")])
    )
    assert completion.reasoning_kinds == ("reasoning.encrypted",)


def test_an_unknown_reasoning_kind_is_kept_not_dropped() -> None:
    """The SDK models unrecognised kinds explicitly; a new one must survive."""
    kinds = parse_reasoning_kinds(SimpleNamespace(reasoning_details=[SimpleNamespace(type="x")]))
    assert kinds == ("x",)


def test_missing_reasoning_details_is_empty_not_a_crash() -> None:
    """Most non-reasoning models return nothing here — a documented state."""
    assert parse_reasoning_kinds(SimpleNamespace(reasoning_details=None)) == ()


# --- refusing rather than guessing ---------------------------------------


def test_null_content_becomes_empty_string() -> None:
    """A refusal can leave content null; downstream grading expects a string."""
    completion = parse_completion(fake_result(content=None, refusal="I can't help with that"))
    assert completion.response == ""
    assert completion.refusal == "I can't help with that"


def test_a_non_string_content_raises_rather_than_being_coerced() -> None:
    """`str()` on a content-parts list would write it in as the model's answer."""
    with pytest.raises(ResponseShapeError, match="expected str or None"):
        parse_text([{"type": "text", "text": "42"}], "message.content")


def test_a_renamed_field_raises_instead_of_returning_empty() -> None:
    """The whole reason this layer exists.

    Under the old `getattr(message, "content", None) or ""` this returned an
    empty response and the run continued, recording blanks that a grader cannot
    distinguish from refusals.
    """
    broken = fake_result()
    del broken.choices[0].message.content
    with pytest.raises(AttributeError):
        parse_completion(broken)


def test_no_choices_raises() -> None:
    with pytest.raises(ResponseShapeError, match="no choices"):
        parse_completion(fake_result(choices=[]))


# --- routing provenance --------------------------------------------------


def test_routing_reports_the_served_endpoint() -> None:
    routing = parse_completion(fake_result()).routing
    assert routing.served_provider == "DeepInfra"
    assert routing.served_model == "qwen/qwen3.6-27b-20260422"
    assert routing.strategy == "direct"
    assert routing.verified


def test_absent_metadata_is_unverified_not_an_error() -> None:
    """Metadata is off by default and need not survive a retry.

    "We were not told" must stay distinct from "the pin was violated", or the
    audit fires on infrastructure noise and gets ignored when it matters.
    """
    routing = parse_completion(fake_result(metadata=None)).routing
    assert routing == Routing()
    assert not routing.verified


def test_metadata_naming_no_selected_endpoint_raises() -> None:
    """Present but uninterpretable is different from absent — and is a bug."""
    unselected = SimpleNamespace(provider="X", model="y", selected=False)
    with pytest.raises(ResponseShapeError, match="exactly one selected endpoint"):
        parse_completion(fake_result(endpoints=[unselected]))


# --- token usage ---------------------------------------------------------
#
# `reasoning` is one of the two headline measures of the whole experiment (the
# source post reports much longer reasoning under the conflicting grader), and
# it sits two levels down a chain of optionals. These exercise that unwrapping.


def fake_usage(reasoning_tokens: int | None = 586, details: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        prompt_tokens=16,
        completion_tokens=675,
        total_tokens=691,
        cost=0.00216512,
        completion_tokens_details=(
            SimpleNamespace(reasoning_tokens=reasoning_tokens) if details else None
        ),
    )


def test_usage_is_flattened_out_of_the_nested_optionals() -> None:
    result = fake_result()
    result.usage = fake_usage()
    usage = parse_completion(result).usage
    assert usage.prompt == 16
    assert usage.completion == 675
    assert usage.total == 691
    assert usage.reasoning == 586
    assert usage.cost_usd == 0.00216512


def test_absent_completion_details_gives_zero_reasoning_not_a_crash() -> None:
    """Non-reasoning models return no details block at all."""
    result = fake_result()
    result.usage = fake_usage(details=False)
    assert parse_completion(result).usage.reasoning == 0
    assert parse_completion(result).usage.completion == 675


def test_null_reasoning_tokens_gives_zero() -> None:
    result = fake_result()
    result.usage = fake_usage(reasoning_tokens=None)
    assert parse_completion(result).usage.reasoning == 0


def test_absent_usage_gives_zeroes() -> None:
    assert parse_completion(fake_result()).usage.total == 0
