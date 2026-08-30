"""One model's gaming rate across every wording of the instruction, and both samplings.

The first figure in the notebook asks which models game. This one holds the model
fixed and varies what was sent to it, which is the only way to tell a property of the
model from a property of one prompt.

Two things vary, and the figure keeps them apart because they are different kinds of
claim. The **wording** of the instruction is a question about the environment: does
"Pick" behave like "Choose". The **sampling** is a question about the measurement:
`top_p=1.0, top_k=0` draws from the whole distribution, while the vendor's
`top_p=0.95, top_k=20` truncates the tail. A rate that moves under the second is not
telling you about the model so much as about the harness that measured it.

Intervals are not decoration here. The paraphrase cells run from 13 to 21 rollouts
against the verbatim cell's 40, so the bars are not equally trustworthy and a reader
comparing bar lengths alone would be misled.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.ticker import PercentFormatter

from odd_number.grades import wilson_interval
from odd_number.rollouts import read_rollouts
from odd_number.traces import Trace
from odd_number.visualisations.figures import CAPTION_INK, short_model

#: The sampling every cell uses unless it was re-run to test the sampling itself.
DEFAULT_TOP_P: float = 1.0
DEFAULT_TOP_K: int = 0

BAR_INK: str = "#a3325c"
#: A cell that exists to vary the sampling rather than the wording, drawn apart so
#: the two kinds of claim are not read as one series.
SAMPLING_INK: str = "#1f6f68"

FIGURE_WIDTH_IN: float = 10.4
SUBTITLE_WRAP: int = 116


@dataclass(frozen=True, slots=True)
class Variant:
    """One cell: an instruction, the sampling it was sent under, and what came back."""

    instruction: str
    top_p: float
    top_k: int
    odd: int
    parseable: int

    @property
    def rate(self) -> float:
        return self.odd / self.parseable if self.parseable else 0.0

    @property
    def interval(self) -> tuple[float, float]:
        return wilson_interval(self.odd, self.parseable)

    @property
    def truncated(self) -> bool:
        """Whether the tail of the distribution was cut before sampling."""
        return self.top_p != DEFAULT_TOP_P or self.top_k != DEFAULT_TOP_K

    @property
    def sampling(self) -> str:
        """The two parameters that differ between cells, written out."""
        return f"top_p {self.top_p:g}, top_k {'off' if self.top_k == 0 else self.top_k}"


def first_line(prompt: str) -> str:
    """The instruction, which is the prompt's first line. The rest is the metadata block."""
    return prompt.split("\n", 1)[0]


def sampling_by_file(results_dir: Path) -> dict[str, tuple[float, int]]:
    """The `top_p` and `top_k` each results file was collected under.

    `Trace` does not carry the sampling, because nothing else in the project needed
    it and adding a field to a type this widely used to serve one figure is the wrong
    trade. It is read here instead, from the first record of each file: a collection
    run pins one sampling for the whole file, which `audit` is what checks.
    """
    found: dict[str, tuple[float, int]] = {}
    for path in sorted(results_dir.glob("*.jsonl")):
        for record in read_rollouts(path):
            sampling = record.get("sampling") or {}
            found[path.name] = (
                float(sampling.get("top_p", DEFAULT_TOP_P)),
                int(sampling.get("top_k", DEFAULT_TOP_K)),
            )
            break
    return found


def variants_of(
    traces: list[Trace],
    sampling: dict[str, tuple[float, int]],
    model: str,
    treatments: set[str],
) -> list[Variant]:
    """One `Variant` per (instruction, sampling) cell of a model's conflict-arm runs.

    Grouped by what was actually sent rather than by file name, so a re-run that
    changes only the sampling becomes its own row against the same instruction
    instead of hiding inside the cell it was meant to be compared with.

    Unparseable answers leave the denominator rather than counting as compliance.
    """
    cells: dict[tuple[str, float, int], list[Trace]] = {}
    for trace in traces:
        if trace.model != model or trace.condition != "conflict":
            continue
        if trace.treatment not in treatments:
            continue
        top_p, top_k = sampling.get(trace.file, (DEFAULT_TOP_P, DEFAULT_TOP_K))
        cells.setdefault((first_line(trace.prompt), top_p, top_k), []).append(trace)
    variants = []
    for (instruction, top_p, top_k), group in cells.items():
        parseable = [t for t in group if t.parity in ("odd", "even")]
        odd = sum(1 for t in parseable if t.parity == "odd")
        variants.append(Variant(instruction, top_p, top_k, odd, len(parseable)))
    return sorted(variants, key=lambda v: (v.truncated, -v.rate, v.instruction))


def paired_by_sampling(variants: list[Variant]) -> list[tuple[Variant, Variant]]:
    """Instructions that were run at both samplings, as (default, truncated) pairs.

    This is the only controlled comparison the sweep contains: same model, same
    prompt, same seeds, one parameter changed.
    """
    plain = {v.instruction: v for v in variants if not v.truncated}
    return [(plain[v.instruction], v) for v in variants if v.truncated and v.instruction in plain]


def sampling_verdict(variants: list[Variant]) -> str:
    """The figure's own answer, computed: does the wording move it, does the sampling.

    Two clauses, because the two questions have different answers and different
    strength of evidence behind them.

    The wording clause asks whether every wording's interval overlaps every other's,
    not whether the rates differ. They do differ, but the paraphrase cells hold 13 to
    21 rollouts, and at that size a difference of a few points is not a finding.

    The sampling clause compares like with like: the same instruction at both
    settings. Comparing the truncated cell against a 13-rollout paraphrase would let
    that cell's very wide interval decide the verdict, which is how an earlier
    version of this function reported a real effect as no effect.
    """
    plain = [v for v in variants if not v.truncated]
    parts: list[str] = []
    if len(plain) > 1:
        mutual = max(v.interval[0] for v in plain) <= min(v.interval[1] for v in plain)
        parts.append(
            f"No wording separates from the other {len(plain) - 1}."
            if mutual
            else f"At least one of the {len(plain)} wordings separates from the others."
        )
    for base, cut in paired_by_sampling(variants):
        touching = cut.interval[0] < base.interval[1]
        parts.append(
            f"Changing the sampling to {cut.sampling} takes the same prompt from"
            f" {base.odd} of {base.parseable} to {cut.odd} of {cut.parseable}"
            + (
                ", though the intervals still touch."
                if touching
                else ", and the intervals separate."
            )
        )
    return " ".join(parts) if parts else "Nothing to compare."


def row_label(variant: Variant, longest: int) -> str:
    """The instruction on one line, its sampling underneath."""
    return f"{textwrap.shorten(variant.instruction, longest)}\n{variant.sampling}"


def draw_variants(axes: Axes, variants: list[Variant]) -> None:
    """One bar per cell, with the interval drawn through it and the count beside it."""
    positions = list(range(len(variants)))
    axes.barh(
        positions,
        [v.rate for v in variants],
        color=[SAMPLING_INK if v.truncated else BAR_INK for v in variants],
        height=0.6,
        zorder=3,
    )
    axes.errorbar(
        [v.rate for v in variants],
        positions,
        xerr=[
            [v.rate - v.interval[0] for v in variants],
            [v.interval[1] - v.rate for v in variants],
        ],
        fmt="none",
        ecolor="#3f3f46",
        elinewidth=1.2,
        capsize=4,
        capthick=1.2,
        zorder=4,
    )
    for row, variant in enumerate(variants):
        axes.annotate(
            f"{variant.odd} of {variant.parseable}",
            xy=(variant.interval[1], row),
            xytext=(8, 0),
            textcoords="offset points",
            va="center",
            size=9.5,
            color=CAPTION_INK,
        )
    axes.set_yticks(positions, [row_label(v, 44) for v in variants])
    axes.invert_yaxis()
    axes.set_xlim(0, 0.78)
    axes.xaxis.set_major_formatter(PercentFormatter(xmax=1, decimals=0))
    axes.set_xlabel("Share of rollouts whose final answer was an odd number", labelpad=10)
    axes.grid(axis="x", color="#eceded", linewidth=0.8)
    axes.set_axisbelow(True)
    axes.tick_params(axis="y", length=0, labelsize=10)
    for side in ("top", "right", "left"):
        axes.spines[side].set_visible(False)
    axes.spines["bottom"].set_color("#d1d5db")


def variants_figure(variants: list[Variant], model: str) -> Figure:
    """The wording-and-sampling sweep for one model, titled with its own verdict."""
    figure, axes = plt.subplots(figsize=(FIGURE_WIDTH_IN, 0.62 * len(variants) + 3.9), dpi=140)
    figure.subplots_adjust(left=0.33, right=0.94, top=0.74, bottom=0.30)
    draw_variants(axes, variants)

    figure.text(
        0.035,
        0.965,
        f"Does the wording move {short_model(model)}'s gaming rate, or does the sampling?",
        size=15,
        weight="bold",
        color="#111827",
        va="top",
    )
    figure.text(
        0.035,
        0.905,
        textwrap.fill(sampling_verdict(variants), SUBTITLE_WRAP),
        size=12,
        color="#111827",
        va="top",
        linespacing=1.5,
    )
    # Under the plot, as the notebook's other figures put their notes. Above, it
    # pushed the bars down the page and had to be read before the picture it was
    # explaining.
    figure.text(
        0.035,
        0.155,
        "\n".join(
            [
                "Each row is one instruction sent at one sampling setting. Both are named on"
                " the left.",
                "Whiskers are 95% Wilson intervals. They are wide on the reworded prompts"
                " because those cells hold 13 to 21 rollouts, against 41 for the original.",
                "The teal bar is not a rewording. It is the original prompt sent again with"
                " the sampling changed.",
            ]
        ),
        size=10,
        color=CAPTION_INK,
        va="top",
        linespacing=1.6,
    )
    return figure
