"""A curve counts only rows that carry an answer, and thin cells stay off the line."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib
import pytest

matplotlib.use("Agg")

from odd_number.branch_curves import (  # noqa: E402
    SOLID_TRIALS,
    BranchCurve,
    BranchRate,
    branch_curve_figure,
    read_branch_curve,
)


def write_sweep(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return path


def row(kept: int, chars: int, parity: str, error: str | None = None) -> dict[str, Any]:
    return {"sentences_kept": kept, "prefix_chars": chars, "parity": parity, "error": error}


def test_a_curve_counts_odd_answers_per_branch_point(tmp_path: Path) -> None:
    path = write_sweep(
        tmp_path / "s.jsonl",
        [row(0, 0, "odd"), row(0, 0, "even"), row(11, 431, "odd")],
    )
    curve = read_branch_curve(path, "plain")
    assert [(r.sentences_kept, r.trials, r.odd) for r in curve.rates] == [(0, 2, 1), (11, 1, 1)]


def test_errored_rows_are_left_out_of_the_denominator(tmp_path: Path) -> None:
    """An HTTP 429 carries no answer; counting it as even would invent a compliance."""
    path = write_sweep(
        tmp_path / "s.jsonl",
        [row(0, 0, "odd"), row(0, 0, "unparseable", error="HTTP 429: ...")],
    )
    (rate,) = read_branch_curve(path, "plain").rates
    assert (rate.trials, rate.odd, rate.rate) == (1, 1, 1.0)


def test_branch_points_come_back_in_prefix_order(tmp_path: Path) -> None:
    path = write_sweep(
        tmp_path / "s.jsonl",
        [row(91, 4589, "odd"), row(0, 0, "even"), row(22, 914, "odd")],
    )
    curve = read_branch_curve(path, "plain")
    assert [r.prefix_chars for r in curve.rates] == [0, 914, 4589]


@pytest.mark.parametrize("trials", [1, SOLID_TRIALS - 1])
def test_a_thin_cell_is_kept_but_stays_off_the_line(trials: int) -> None:
    """Leftovers from a coarser grid are drawn, and a line through them would read
    as a measurement."""
    curve = BranchCurve("plain", tuple([BranchRate(23, 932, trials, trials)]))
    assert curve.rates and curve.solid == ()


def test_a_well_sampled_cell_joins_the_line() -> None:
    curve = BranchCurve("plain", (BranchRate(0, 0, SOLID_TRIALS, 3),))
    assert len(curve.solid) == 1


def test_a_zero_rate_still_gets_an_honest_interval() -> None:
    low, high = BranchRate(0, 0, 30, 0).interval
    assert low == 0.0
    assert 0.0 < high < 0.2


def test_more_curves_than_inks_is_refused() -> None:
    """Two curves silently sharing one colour would make the figure unreadable."""
    curves = [BranchCurve(f"c{i}", (BranchRate(0, 0, 30, 1),)) for i in range(3)]
    with pytest.raises(ValueError, match="inks defined"):
        branch_curve_figure(curves, "t", "c")


def test_a_figure_draws_both_curves() -> None:
    curves = [
        BranchCurve("plain", (BranchRate(0, 0, 30, 7), BranchRate(91, 4589, 30, 30))),
        BranchCurve("affirming", (BranchRate(0, 0, 30, 0), BranchRate(91, 4589, 30, 4))),
    ]
    figure = branch_curve_figure(curves, "title", "caption")
    (axes,) = figure.axes
    assert [
        line.get_label() for line in axes.get_lines() if not line.get_label().startswith("_")
    ] == [
        "plain",
        "affirming",
    ]
