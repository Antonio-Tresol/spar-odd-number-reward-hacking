"""P(odd) against how much of a trace was held as a prefix.

One curve is one branch-resampling sweep: at each branch point the fraction of
resamples that answered odd, with a Wilson interval. Curves share a pair of axes
so they can be read against each other: the same prefixes under two prompts,
which is the comparison `Q1.H8.E2` rests on, or two source traces under one
prompt.

Branch points are placed on the x axis by prefix characters rather than by
sentence index, so a curve is read against how much reasoning the model was
given. Sweeps at different `--points` grids land on different sentence indices
and still plot against a common axis.

Colours and the caption block follow `figures.py`, which this imports rather
than restates.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.ticker import PercentFormatter

from odd_number.figures import CAPTION_INK, CONTROL_INK, ODD_INK
from odd_number.grades import wilson_interval

#: A branch point carrying fewer resamples than this is drawn hollow and left out
#: of the line. Cells of one or two rows are leftovers from a coarser grid, and a
#: line drawn through them reads as a measurement rather than as a stray.
SOLID_TRIALS: int = 10

#: Inks for the second and third curves. The first takes `ODD_INK` from the
#: shared palette, which is the colour the gaming-rate figure gives an odd
#: answer, so a plain-prompt odd curve reads the same way on both figures.
SECOND_INK: str = "#1565c0"
THIRD_INK: str = "#2e7d32"

#: Room above and below the 0-1 axis, so the 0% and 100% markers and their
#: intervals sit inside the frame instead of on it.
Y_PAD: float = 0.06


@dataclass(frozen=True, slots=True)
class BranchRate:
    """One branch point: how much prefix, how many resamples, how many odd."""

    sentences_kept: int
    prefix_chars: int
    trials: int
    odd: int

    @property
    def rate(self) -> float:
        return self.odd / self.trials if self.trials else 0.0

    @property
    def interval(self) -> tuple[float, float]:
        return wilson_interval(self.odd, self.trials)

    @property
    def is_solid(self) -> bool:
        return self.trials >= SOLID_TRIALS


@dataclass(frozen=True, slots=True)
class BranchCurve:
    """Every branch point of one sweep, in prefix order."""

    label: str
    rates: tuple[BranchRate, ...]

    @property
    def solid(self) -> tuple[BranchRate, ...]:
        return tuple(rate for rate in self.rates if rate.is_solid)


def read_branch_curve(path: Path, label: str) -> BranchCurve:
    """Load one sweep's rows and count odd answers per branch point.

    Rows that recorded an error carry no answer and are dropped, which is the
    same rule `load_completed_keys` applies when deciding what a resumed sweep
    still owes.
    """
    trials: dict[tuple[int, int], list[str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("error") is not None:
            continue
        key = (row["sentences_kept"], row["prefix_chars"])
        trials.setdefault(key, []).append(row["parity"])
    rates = tuple(
        BranchRate(
            sentences_kept=kept,
            prefix_chars=chars,
            trials=len(parities),
            odd=sum(1 for parity in parities if parity == "odd"),
        )
        for (kept, chars), parities in sorted(trials.items())
    )
    return BranchCurve(label=label, rates=rates)


def draw_curve(axes: Axes, curve: BranchCurve, ink: str) -> None:
    """One curve: a line through the well-sampled points, every point marked."""
    solid = curve.solid
    axes.plot(
        [rate.prefix_chars for rate in solid],
        [rate.rate for rate in solid],
        color=ink,
        linewidth=1.8,
        zorder=3,
        label=curve.label,
    )
    for rate in curve.rates:
        low, high = rate.interval
        axes.vlines(
            rate.prefix_chars,
            low,
            high,
            color=ink,
            linewidth=1.0,
            alpha=0.55 if rate.is_solid else 0.3,
            zorder=2,
        )
        axes.plot(
            [rate.prefix_chars],
            [rate.rate],
            marker="o",
            markersize=5.5 if rate.is_solid else 4.0,
            color=ink if rate.is_solid else "white",
            markeredgecolor=ink,
            markeredgewidth=1.2,
            zorder=4,
        )


def branch_curve_figure(curves: list[BranchCurve], title: str, caption: str) -> Figure:
    """Every curve on one pair of axes, with a caption block beneath.

    Raises:
        ValueError: when asked for more curves than the palette names.
    """
    inks = (ODD_INK, SECOND_INK, THIRD_INK)
    if len(curves) > len(inks):
        raise ValueError(f"{len(curves)} curves, {len(inks)} inks defined")
    figure, axes = plt.subplots(figsize=(9.0, 5.4))
    for curve, ink in zip(curves, inks, strict=False):
        draw_curve(axes, curve, ink)
    axes.set_ylim(-Y_PAD, 1 + Y_PAD)
    axes.yaxis.set_major_formatter(PercentFormatter(xmax=1.0))
    axes.set_xlabel("characters of the model's own reasoning held as a prefix")
    axes.set_ylabel("P(odd answer)")
    axes.set_title(title, loc="left", fontsize=12)
    axes.grid(axis="y", color=CONTROL_INK, alpha=0.15, linewidth=0.7)
    for side in ("top", "right"):
        axes.spines[side].set_visible(False)
    axes.legend(frameon=False, loc="lower right", fontsize=9)
    figure.subplots_adjust(bottom=0.30)
    figure.text(0.035, 0.10, caption, fontsize=8.5, color=CAPTION_INK, va="top", wrap=True)
    return figure
