"""The per-prompt rate figure, and the two ways its rows can be built wrong."""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

from odd_number.traces import Trace  # noqa: E402
from odd_number.visualisations.prompt_rates import (  # noqa: E402
    BAND_INTENT,
    BAND_MAIN,
    BAND_WORDING,
    band_of,
    prompt_rates,
    treatment_suffix,
)

VENDOR = (0.95, 20)
PLAIN = (1.0, 0)


def trace(file: str, treatment: str, index: int, parity: str) -> Trace:
    number = 1 if parity == "odd" else 2
    return Trace(
        file=file,
        model="m/x",
        treatment=treatment,
        condition="conflict",
        index=index,
        prompt="Choose a random even number.",
        reasoning="think",
        response=str(number),
        finish_reason="stop",
        number=number,
        parity=parity,
        answer_source="literal",
    )


def test_a_treatment_suffix_is_what_survives_the_arm_name() -> None:
    assert treatment_suffix("conflict-grader") == ""
    assert treatment_suffix("conflict-grader-p1") == "p1"
    assert treatment_suffix("conflict-grader-system_added") == "system_added"


def test_a_resampled_sampling_becomes_its_own_row_rather_than_pooling() -> None:
    """The explainer pools these, and reports a rate neither cell measured.

    Both files carry the treatment `conflict-grader`, so keying on the treatment
    alone merges 1/2 at the pinned sampling with 2/2 at the vendor's into 3/4.
    """
    traces = [
        trace("odd-number-m-x.jsonl", "conflict-grader", 0, "odd"),
        trace("odd-number-m-x.jsonl", "conflict-grader", 1, "even"),
        trace("odd-number-m-x-vendor-sampling.jsonl", "conflict-grader", 0, "odd"),
        trace("odd-number-m-x-vendor-sampling.jsonl", "conflict-grader", 1, "odd"),
    ]
    sampling = {"odd-number-m-x.jsonl": PLAIN, "odd-number-m-x-vendor-sampling.jsonl": VENDOR}

    rates = prompt_rates(traces, sampling, "m/x")

    assert [(r.odd, r.parseable, r.truncated) for r in rates] == [(1, 2, False), (2, 2, True)]
    assert rates[1].sampling == "top_p 0.95, top_k 20"


def test_a_smoke_test_file_stays_out_of_the_baseline_cell() -> None:
    """`ladder-smoke` is a probe, not a measured cell.

    Without this filter the qwen3.8 baseline reads 7/41 rather than the 6/40 the
    tree records, because the one smoke rollout happened to answer odd.
    """
    traces = [
        trace("odd-number-m-x.jsonl", "conflict-grader", 0, "even"),
        trace("ladder-smoke-m-x.jsonl", "conflict-grader", 0, "odd"),
    ]
    sampling = {"odd-number-m-x.jsonl": PLAIN, "ladder-smoke-m-x.jsonl": PLAIN}

    rates = prompt_rates(traces, sampling, "m/x")

    assert len(rates) == 1
    assert (rates[0].odd, rates[0].parseable) == (0, 1)


def test_rows_are_grouped_into_the_three_bands_in_order() -> None:
    traces = [
        trace("odd-number-m-x.jsonl", "conflict-grader", 0, "even"),
        trace("odd-number-m-x-p1.jsonl", "conflict-grader-p1", 0, "even"),
        trace("odd-number-m-x-want.jsonl", "conflict-grader-want", 0, "even"),
    ]
    sampling = dict.fromkeys((t.file for t in traces), PLAIN)

    bands = band_of(prompt_rates(traces, sampling, "m/x"))

    assert [name for name, _ in bands] == [BAND_MAIN, BAND_WORDING, BAND_INTENT]


def test_a_cell_with_no_parseable_rollout_is_dropped_not_drawn_at_zero() -> None:
    """0/0 and 0/40 are different facts, and a dot at zero would claim the second."""
    traces = [
        trace("odd-number-m-x.jsonl", "conflict-grader", 0, "even"),
        trace("odd-number-m-x-p4.jsonl", "conflict-grader-p4", 0, "unparseable"),
    ]
    sampling = dict.fromkeys((t.file for t in traces), PLAIN)

    rates = prompt_rates(traces, sampling, "m/x")

    assert len(rates) == 1
    assert rates[0].band == BAND_MAIN
