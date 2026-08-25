"""Tests for the routing pins and the provenance audit.

These test one thing: that a results file cannot silently come from weights or a
provider other than the ones it claims. Every assertion here corresponds to a
way that could happen.

The lens-mismatch test is the odd one out — it asserts a *defect* in the
available artefacts (the pre-fitted gemma-4 lens was fitted on base weights, not
the instruct checkpoint we serve). It is pinned as a test so that the mismatch
has to be resolved by re-fitting a lens, not by editing the field that records
it. See `notes/model-selection.md` for the config.yaml this reads from.

Run:  uv run pytest tests/test_pinning.py
"""

from __future__ import annotations

import json
from dataclasses import replace

from odd_number.environment import Treatment
from odd_number.pinned_models import (
    HOSTABLE_MODELS,
    LADDER_QUANTIZATION,
    PINNED_MODELS,
    PINNED_MODELS_BY_SLUG,
    build_routing_body,
    resolve_pinned_model,
)
from odd_number.provenance import audit_pins, find_pin_mismatches, normalise_provider_key
from odd_number.rollouts import Rollout, RolloutRequest, collect_rollout


def pinned_rollout(**overrides: object) -> dict[str, object]:
    """One results-file record whose pins held, before overrides."""
    record: dict[str, object] = {
        "treatment": "conflict-grader",
        "index": 0,
        "error": None,
        "provider": "deepinfra/fp8",
        "snapshot": "qwen/qwen3.6-27b-20260422",
        "served_provider": "DeepInfra",
        "served_model": "qwen/qwen3.6-27b-20260422",
        "routing_strategy": "direct",
    }
    return {**record, **overrides}


# --- every model is actually pinned ----------------------------------------


def test_every_pinned_model_sends_a_snapshot_not_a_bare_alias() -> None:
    """The hostable models are what we would self-host, so their weights must be nailed down.

    OpenRouter is free to repoint an alias at a newer checkpoint. A dated slug
    is the only thing that survives that.
    """
    for model in HOSTABLE_MODELS:
        assert model.snapshot != model.slug, f"{model.slug} is pinned to an alias"


def test_snapshots_belong_to_the_model_they_claim() -> None:
    """Catches a transposed or mistyped snapshot pointing at a different model."""
    for model in PINNED_MODELS:
        assert model.snapshot.startswith(model.slug), model.slug


def test_provider_tags_name_a_provider() -> None:
    for model in PINNED_MODELS:
        assert model.provider, f"{model.slug} has no pinned provider"


def test_routing_refuses_substitutes() -> None:
    """Without these two flags OpenRouter reroutes silently on unavailability."""
    body = build_routing_body("novita/bf16")
    assert body["order"] == ["novita/bf16"]
    assert body["allow_fallbacks"] is False
    assert body["require_parameters"] is True


def test_resolve_rejects_a_model_that_is_not_pinned() -> None:
    """An unpinned run produces a file that cannot be compared with a pinned one."""
    try:
        resolve_pinned_model("deepseek/deepseek-r1")
    except KeyError as exc:
        assert "is not a pinned model" in exc.args[0]
        assert "qwen/qwen3.6-27b" in exc.args[0], "the error should list the alternatives"
    else:
        raise AssertionError("an unpinned model was accepted")


# --- lens/checkpoint agreement -------------------------------------------


def test_gemma_lens_is_known_not_to_match_the_served_weights() -> None:
    """The pre-fitted gemma-4 lens is fitted on `google/gemma-4-31B`, the base
    model, while OpenRouter serves `google/gemma-4-31B-it`. Treating them as
    interchangeable would produce readouts from the wrong weights.
    """
    gemma = PINNED_MODELS_BY_SLUG["google/gemma-4-31b-it"]
    assert gemma.lens_ckpt == "google/gemma-4-31B"
    assert gemma.hf_id == "google/gemma-4-31B-it"
    assert not gemma.lens_matches_served_weights


def test_only_a_lens_whose_provenance_was_read_counts_as_matching() -> None:
    """`qwen3.5-27b` is the only pinned model's lens whose source checkpoint was verified.

    Its `config.yaml` records `hf_model_name: "Qwen/Qwen3.5-27B"`, matching the
    served weights. The others are unknowns, not matches: `qwen3.6-27b`'s lens
    directory has no config at all, and `qwen3.8-27b`'s community README claims
    `Qwen/Qwen3.8-27B` while its own fit command names `eyes-ml/Qwen3.8-27B`.
    """
    assert PINNED_MODELS_BY_SLUG["qwen/qwen3.5-27b"].lens_matches_served_weights
    for slug in ("qwen/qwen3.6-27b", "qwen/qwen3.8-27b"):
        assert not PINNED_MODELS_BY_SLUG[slug].lens_matches_served_weights, slug


def test_an_unread_provenance_never_counts_as_a_match() -> None:
    """Guards the mechanism itself: filling in lens_ckpt by hand must not be
    enough to make a lens 'match'. Only reading the artefact is.
    """
    guessed = replace(PINNED_MODELS_BY_SLUG["qwen/qwen3.6-27b"], lens_ckpt="Qwen/Qwen3.6-27B")
    assert not guessed.lens_matches_served_weights
    assert replace(guessed, lens_ckpt_source="config.yaml").lens_matches_served_weights


# --- provenance audit ----------------------------------------------------


def test_provider_names_and_tags_compare_equal() -> None:
    """The pin is a tag; the generation record is a display name. Every pairing
    below was observed live, so each is a real case the audit must not flag.
    """
    for tag, name in (
        ("deepinfra/fp8", "DeepInfra"),
        ("akashml/bf16", "AkashML"),
        ("novita/bf16", "Novita"),
        ("open-inference/bf16", "OpenInference"),
        ("coreweave/fp8", "CoreWeave"),
    ):
        assert normalise_provider_key(tag) == normalise_provider_key(name), tag


def test_a_matching_call_reports_no_mismatch() -> None:
    assert find_pin_mismatches(pinned_rollout()) == []


def test_a_substituted_provider_is_caught() -> None:
    found = find_pin_mismatches(pinned_rollout(served_provider="Novita"))
    assert len(found) == 1
    assert "provider" in found[0]


def test_a_repointed_snapshot_is_caught() -> None:
    """The failure this whole mechanism exists for: same alias, new weights."""
    found = find_pin_mismatches(pinned_rollout(served_model="qwen/qwen3.6-27b-20260901"))
    assert len(found) == 1
    assert "snapshot" in found[0]


def test_a_non_direct_routing_strategy_is_caught() -> None:
    """`allow_fallbacks=False` should make a reroute impossible, so anything
    other than `direct` means an assumption this project relies on has stopped
    holding — even when the endpoint still matches.
    """
    found = find_pin_mismatches(pinned_rollout(routing_strategy="fallback"))
    assert len(found) == 1
    assert "routing" in found[0]


def test_absent_provenance_is_not_a_mismatch() -> None:
    """Absent evidence is not evidence of substitution — it is a gap."""
    unknown = pinned_rollout(served_provider=None, served_model=None, routing_strategy=None)
    assert find_pin_mismatches(unknown) == []


def test_audit_counts_unverified_separately_from_problems(tmp_path) -> None:
    """An audit that fires on missing metadata would cry wolf on infrastructure
    noise, and an audit that cries wolf gets ignored when it matters.
    """
    path = tmp_path / "r.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(r)
            for r in (
                pinned_rollout(),
                pinned_rollout(index=1, served_provider=None, served_model=None),
                pinned_rollout(index=2, error="boom"),
            )
        ),
        encoding="utf-8",
    )
    report = audit_pins(path)
    assert report.checked == 2, "the errored rollout is not a pin failure"
    assert report.verified == 1
    assert report.unverified == 1
    assert report.clean


# --- what a rollout records ----------------------------------------------


def test_a_rollout_records_the_snapshot_and_provider_it_used() -> None:
    """The alias alone does not identify the run, so both must reach the file."""
    model = PINNED_MODELS_BY_SLUG["qwen/qwen3.6-27b"]
    rollout = collect_rollout(None, RolloutRequest(model, Treatment(condition="conflict"), 0))
    assert isinstance(rollout, Rollout)
    assert rollout.model == "qwen/qwen3.6-27b"
    assert rollout.snapshot == "qwen/qwen3.6-27b-20260422"
    assert rollout.provider == "deepinfra/fp8"


# --- the ladder is a controlled comparison -------------------------------


def test_the_three_qwen_rungs_share_an_architecture() -> None:
    """The ladder's whole premise: identical size, three post-training generations.

    If these ever diverge, a difference between rungs stops being attributable
    to post-training and the comparison silently becomes about scale.
    """
    rungs = [
        PINNED_MODELS_BY_SLUG[s]
        for s in ("qwen/qwen3.5-27b", "qwen/qwen3.6-27b", "qwen/qwen3.8-27b")
    ]
    assert len({c.params_b for c in rungs}) == 1


def test_the_three_qwen_rungs_share_a_quantization() -> None:
    """Otherwise a rung-to-rung difference could be numeric precision.

    Holding the provider fixed instead would be stronger, but no provider
    serves all three rungs reliably — see LADDER_QUANTIZATION for the two that
    were tried and why they failed.
    """
    rungs = [
        PINNED_MODELS_BY_SLUG[s]
        for s in ("qwen/qwen3.5-27b", "qwen/qwen3.6-27b", "qwen/qwen3.8-27b")
    ]
    assert {c.quantization for c in rungs} == {LADDER_QUANTIZATION}
    assert all(c.provider.endswith(f"/{LADDER_QUANTIZATION}") for c in rungs)


def test_the_ladders_provider_confound_is_confined_to_one_rung() -> None:
    """Two of three rungs share a provider; the comparison must name the third."""
    rungs = [
        PINNED_MODELS_BY_SLUG[s]
        for s in ("qwen/qwen3.5-27b", "qwen/qwen3.6-27b", "qwen/qwen3.8-27b")
    ]
    providers = [c.provider.split("/")[0] for c in rungs]
    assert len(set(providers)) == 2, "the ladder should span at most two providers"
    assert providers.count("deepinfra") == 2
