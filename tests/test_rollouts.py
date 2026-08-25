"""Tests for collection: resume bookkeeping and seeds.

There are no retry tests, and that is the point: retries belong to the
OpenRouter SDK's RetryConfig, which already does backoff-with-jitter and honours
Retry-After / retry-after-ms headers. Re-testing a vendor's retry loop tests the
vendor. What is tested here is what this project actually decides.

Reading the SDK's response shape is `completions.py`'s job and is tested in
`test_completions.py`; nothing in this module touches a `ChatResult`.

Run:  uv run pytest tests/test_rollouts.py
"""

from __future__ import annotations

import json
from pathlib import Path

from odd_number.environment import Treatment
from odd_number.pinned_models import PINNED_MODELS_BY_SLUG
from odd_number.rollouts import (
    RolloutRequest,
    collect_rollout,
    collect_rollouts,
    derive_seed,
    load_completed_keys,
)
from odd_number.sampling import SamplingParams

# --- resume bookkeeping --------------------------------------------------


def test_done_keys_skips_errored_rollouts(tmp_path: Path) -> None:
    """An errored rollout must be re-attempted, not counted as collected."""
    path = tmp_path / "r.jsonl"
    path.write_text(
        json.dumps({"treatment": "conflict-grader", "index": 0, "error": None})
        + "\n"
        + json.dumps({"treatment": "conflict-grader", "index": 1, "error": "boom"})
        + "\n",
        encoding="utf-8",
    )
    assert load_completed_keys(path) == {("conflict-grader", 0)}


def test_done_keys_retries_a_provider_abort(tmp_path: Path) -> None:
    """A `finish_reason="error"` row has no answer and was not the model's doing."""
    path = tmp_path / "r.jsonl"
    path.write_text(
        json.dumps(
            {"treatment": "conflict-grader", "index": 0, "error": None, "finish_reason": "error"}
        )
        + "\n"
        + json.dumps(
            {"treatment": "conflict-grader", "index": 1, "error": None, "finish_reason": "length"}
        )
        + "\n",
        encoding="utf-8",
    )
    assert load_completed_keys(path) == {("conflict-grader", 1)}


def test_done_keys_tolerates_a_torn_final_line(tmp_path: Path) -> None:
    """A hard kill mid-write must not make the whole results file unreadable."""
    path = tmp_path / "r.jsonl"
    path.write_text(
        json.dumps({"treatment": "agree-grader", "index": 0, "error": None}) + '\n{"var',
        encoding="utf-8",
    )
    assert load_completed_keys(path) == {("agree-grader", 0)}


def test_done_keys_on_a_missing_file_is_empty(tmp_path: Path) -> None:
    assert load_completed_keys(tmp_path / "nope.jsonl") == set()


# --- seeds ---------------------------------------------------------------


def test_seed_is_pinned_to_a_literal_value() -> None:
    """Pinned, not just self-consistent.

    An in-process "call it twice, get the same answer" test passes happily for
    `hash()` too — the randomisation is per *process*, not per call. Only a
    hardcoded expected value catches a seed that silently changes between runs.
    """
    assert derive_seed("conflict-grader", 0) == 2_450_989_572
    assert derive_seed("agree-grader", 0) == 3_137_547_086


def test_seed_varies_with_both_label_and_index() -> None:
    assert derive_seed("conflict-grader", 0) != derive_seed("conflict-grader", 1)
    assert derive_seed("conflict-grader", 0) != derive_seed("agree-grader", 0)


# --- what a rollout records about how it was drawn -----------------------


def test_a_rollout_records_the_sampling_it_used() -> None:
    """A gaming rate is an estimate of a distribution, and the sampling
    parameters *are* that distribution. A results file that does not carry them
    cannot be compared with one collected after someone edited a literal.
    """
    sampling = SamplingParams(temperature=0.7, top_p=0.9, top_k=None, max_tokens=512)
    request = RolloutRequest(
        model=PINNED_MODELS_BY_SLUG["qwen/qwen3.6-27b"],
        treatment=Treatment(condition="conflict"),
        index=0,
        sampling=sampling,
    )
    rollout = collect_rollout(None, request)
    assert rollout.sampling == {
        "temperature": 0.7,
        "top_p": 0.9,
        "top_k": None,
        "max_tokens": 512,
    }


def test_temperature_defaults_to_one_so_the_rate_is_measurable() -> None:
    """Temperature 0 would repeat the modal answer n times and collapse the
    gaming rate to 0% or 100% with nothing in between.
    """
    assert SamplingParams().temperature == 1.0


def test_top_k_can_be_omitted_entirely() -> None:
    """None means 'do not send the parameter', which is a different request
    from sending 0 — see sampling.py for why neither option is free.
    """
    assert "top_k" not in SamplingParams(top_k=None).as_request_kwargs()
    assert SamplingParams(top_k=0).as_request_kwargs()["top_k"] == 0


def test_every_sampling_parameter_is_sent_explicitly() -> None:
    """Unsent is not neutral: it hands the value to a per-provider default,
    which is the seam the ladder's pins exist to close.
    """
    sent = SamplingParams().as_request_kwargs()
    assert {"temperature", "top_p", "top_k", "max_tokens"} <= set(sent)


# --- concurrency ---------------------------------------------------------


def test_concurrent_collection_yields_every_request_exactly_once() -> None:
    """Workers change the order rollouts land in, never which ones land."""
    requests = [
        RolloutRequest(
            model=PINNED_MODELS_BY_SLUG["qwen/qwen3.6-27b"], treatment=treatment, index=index
        )
        for treatment in (Treatment(condition="conflict"), Treatment(condition="agree"))
        for index in range(6)
    ]
    sequential = list(collect_rollouts(None, requests, workers=1))
    concurrent = list(collect_rollouts(None, requests, workers=4))
    keyed = {(r.treatment, r.index): r for r in concurrent}
    assert len(keyed) == len(requests)
    for rollout in sequential:
        assert keyed[(rollout.treatment, rollout.index)] == rollout


# --- endpoints without seed ----------------------------------------------


def test_a_model_without_seed_support_records_no_seed() -> None:
    """The results file must not claim a seed the endpoint never received."""
    from dataclasses import replace

    unseeded = replace(PINNED_MODELS_BY_SLUG["qwen/qwen3.6-27b"], seed_supported=False)
    request = RolloutRequest(model=unseeded, treatment=Treatment(condition="agree"), index=0)
    assert collect_rollout(None, request).seed is None
    seeded = RolloutRequest(
        model=PINNED_MODELS_BY_SLUG["qwen/qwen3.6-27b"],
        treatment=Treatment(condition="agree"),
        index=0,
    )
    assert collect_rollout(None, seeded).seed == derive_seed("agree-grader", 0)
