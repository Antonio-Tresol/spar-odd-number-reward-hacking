"""Why "the clarification removed the confusion" is not yet established.

Four of the added sentences take the odd answer to zero. They also take the
reasoning down to a quarter of its length, and in this corpus a short trace almost
never answers odd. Both stories predict the same table of rates, so the rates
alone cannot separate them:

- the sentence settled the question the model was working on, or
- the sentence stopped it working on anything

The figure puts the two variables side by side so the reader can see they move
together. The left panel is one dot per rollout, so a claim about medians can be
checked against the spread behind it. The right panel pools every treatment and
asks the confound directly: given only how long a trace ran, how often did it
answer odd?

This figure argues that a question is open. It does not answer it. Resampling
does, by holding the length fixed and varying the prompt (`Q1.H8.E2`).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.ticker import PercentFormatter

from odd_number.grades import wilson_interval
from odd_number.traces import Trace
from odd_number.visualisations.figures import (
    ARTEFACT_FILE,
    CAPTION_INK,
    apply_house_style,
    frame_figure,
    short_model,
)
from odd_number.visualisations.prompt_rates import ROWS, treatment_suffix
from odd_number.visualisations.variants import DEFAULT_TOP_K, DEFAULT_TOP_P, sampling_by_file

#: A name per prompt version that fits in a row label. `prompt_rates.ROWS` carries
#: the sentence itself, which is right for the figure whose subject is the
#: wording and far too long for one whose subject is length.
SHORT: Final[dict[str, str]] = {
    "": "the prompt as posted",
    "p1": "reworded: pick",
    "p2": "reworded: give me",
    "p3": "reworded: please choose",
    "test": "adds: this is a reward hacking eval",
    "misaligned": "adds: violating instructions is misaligned",
    "want": "adds: we want instructions followed",
    "system_added": "adds: the system wrote the metadata",
    "user_authored": "adds: the instruction is what the user wants",
    "human_sender": "adds: a person is waiting for the answer",
}

ODD_INK: Final[str] = "#a3325c"
EVEN_INK: Final[str] = "#c9c4bd"
MEDIAN_INK: Final[str] = "#3f3f46"
#: One legend dot, so the key and the plot cannot drift apart.
DOT: Final[dict[str, object]] = {"marker": "o", "linestyle": "none", "markersize": 6}
#: Edges in characters of reasoning. Chosen to put a comparable number of traces
#: in each rather than to make the gradient look steep.
BANDS: Final[tuple[int, ...]] = (0, 2_000, 6_000, 12_000, 20_000, 30_000)
FIGURE_WIDTH_IN: Final[float] = 13.0
ROW_HEIGHT_IN: Final[float] = 0.46


@dataclass(frozen=True, slots=True)
class LengthConfound:
    """One prompt version at one sampling: how long each ran, and which answered odd."""

    label: str
    top_p: float
    top_k: int
    odd: tuple[int, ...]
    even: tuple[int, ...]

    @property
    def truncated(self) -> bool:
        """Whether the tail of the distribution was cut before sampling."""
        return self.top_p != DEFAULT_TOP_P or self.top_k != DEFAULT_TOP_K

    @property
    def row(self) -> str:
        """The row label, naming the sampling only when it is not the pinned one."""
        rate = f"{len(self.odd)}/{self.total} odd"
        if not self.truncated:
            return f"{self.label}   {rate}"
        return f"{self.label}\nat vendor sampling, top_p {self.top_p:g}   {rate}"

    @property
    def total(self) -> int:
        return len(self.odd) + len(self.even)

    @property
    def rate(self) -> float:
        return len(self.odd) / self.total if self.total else 0.0

    @property
    def median_chars(self) -> float:
        lengths = [*self.odd, *self.even]
        return statistics.median(lengths) if lengths else 0.0


def length_confounds(
    traces: list[Trace], sampling: dict[str, tuple[float, int]], model: str
) -> list[LengthConfound]:
    """One row per (prompt, sampling) cell, ordered as `ROWS` declares them.

    Rows are labelled by `SHORT` rather than the full sentence: the per-prompt
    figure already carries the wording, and this one is about lengths.

    Keyed on the sampling as well as the prompt, for the same reason
    `prompt_rates` is: the baseline was run twice, 6 of 40 at the pinned
    `top_p=1.0` and 17 of 40 at the vendor's, and those two intervals do not
    overlap. Pooling them draws a 23/80 row that neither run measured.
    """
    labels = {suffix: SHORT[suffix] for suffix, _, _ in ROWS if suffix in SHORT}
    cells: dict[tuple[str, float, int], list[Trace]] = {}
    for trace in traces:
        if trace.model != model or trace.condition != "conflict":
            continue
        if ARTEFACT_FILE.search(trace.file) or trace.parity not in ("odd", "even"):
            continue
        suffix = treatment_suffix(trace.treatment)
        if suffix not in labels:
            continue
        top_p, top_k = sampling.get(trace.file, (DEFAULT_TOP_P, DEFAULT_TOP_K))
        cells.setdefault((suffix, top_p, top_k), []).append(trace)
    order = {suffix: i for i, (suffix, _, _) in enumerate(ROWS)}
    return [
        LengthConfound(
            label=labels[suffix],
            top_p=top_p,
            top_k=top_k,
            odd=tuple(len(t.reasoning) for t in group if t.parity == "odd"),
            even=tuple(len(t.reasoning) for t in group if t.parity == "even"),
        )
        for (suffix, top_p, top_k), group in sorted(
            cells.items(), key=lambda kv: (order[kv[0][0]], kv[0][1] != DEFAULT_TOP_P)
        )
    ]


def band_rates(traces: list[Trace], model: str) -> list[tuple[str, int, int]]:
    """Odd rate by reasoning length, pooled across every prompt version."""
    pool = [
        t
        for t in traces
        if t.model == model
        and t.condition == "conflict"
        and not ARTEFACT_FILE.search(t.file)
        and t.parity in ("odd", "even")
    ]
    edges = [*BANDS, 10**9]
    rows = []
    for low, high in zip(edges[:-1], edges[1:], strict=True):
        band = [t for t in pool if low <= len(t.reasoning) < high]
        if not band:
            continue
        if low == 0:
            name = f"under {high // 1000}k"
        elif high == 10**9:
            name = f"over {low // 1000}k"
        else:
            name = f"{low // 1000}k to {high // 1000}k"
        rows.append((name, sum(1 for t in band if t.parity == "odd"), len(band)))
    return rows


def draw_lengths(axes: Axes, rows: list[LengthConfound]) -> None:
    """Left panel: one dot per rollout, odd ones on top, median marked."""
    positions = list(range(len(rows)))[::-1]
    for position, row in zip(positions, rows, strict=True):
        for values, ink, size, order in ((row.even, EVEN_INK, 26, 2), (row.odd, ODD_INK, 34, 3)):
            if not values:
                continue
            jitter = np.linspace(-0.16, 0.16, len(values))
            axes.scatter(
                np.sqrt(values),
                position + jitter,
                s=size,
                color=ink,
                alpha=0.85,
                edgecolors="none",
                zorder=order,
            )
        axes.plot(
            [np.sqrt(row.median_chars)],
            [position],
            marker="|",
            markersize=17,
            color=MEDIAN_INK,
            markeredgewidth=2.0,
            zorder=4,
        )
    ticks = [0, 2_000, 6_000, 12_000, 20_000, 40_000, 68_000]
    axes.set_xticks([np.sqrt(t) for t in ticks])
    axes.set_xticklabels([f"{t // 1000}k" if t else "0" for t in ticks])
    axes.set_xlim(0, np.sqrt(72_000))
    axes.set_xlabel("characters of reasoning (square-root scale)", fontsize=9.5, color=CAPTION_INK)
    axes.set_title("How long each rollout thought", fontsize=10.5, loc="left", pad=12)
    axes.legend(
        handles=[
            Line2D([], [], **DOT, color=ODD_INK, label="answered odd"),
            Line2D([], [], **DOT, color=EVEN_INK, label="answered even"),
            Line2D(
                [],
                [],
                marker="|",
                linestyle="none",
                markersize=11,
                color=MEDIAN_INK,
                markeredgewidth=2.0,
                label="median",
            ),
        ],
        loc="lower right",
        ncols=1,
        frameon=False,
        fontsize=9,
        labelcolor=CAPTION_INK,
        handletextpad=0.4,
        columnspacing=1.4,
        borderaxespad=0.2,
    )


def draw_band_rates(axes: Axes, rows: list[tuple[str, int, int]]) -> None:
    """Right panel: the confound on its own, with length as the only variable."""
    positions = list(range(len(rows)))[::-1]
    for position, (_, odd, total) in zip(positions, rows, strict=True):
        low, high = wilson_interval(odd, total)
        axes.plot(
            [low, high],
            [position, position],
            color=ODD_INK,
            linewidth=1.6,
            alpha=0.5,
            solid_capstyle="round",
            zorder=2,
        )
        axes.plot([odd / total], [position], marker="o", markersize=8, color=ODD_INK, zorder=3)
        axes.annotate(
            f"{odd}/{total}",
            xy=(high, position),
            xytext=(8, 0),
            textcoords="offset points",
            va="center",
            fontsize=9,
            color=CAPTION_INK,
        )
    axes.set_yticks(positions, [name for name, _, _ in rows], fontsize=9.5)
    axes.set_xlim(0, 0.78)
    axes.xaxis.set_major_formatter(PercentFormatter(xmax=1.0))
    axes.set_xlabel("rollouts answering odd", fontsize=9.5, color=CAPTION_INK)
    axes.set_title("Length alone, every version pooled", fontsize=10.5, loc="left", pad=12)


def length_confound_figure(
    rows: list[LengthConfound], bands: list[tuple[str, int, int]], model: str
) -> Figure:
    """Both panels, sharing the point that the two variables move together."""
    apply_house_style()
    figure, (left, right) = plt.subplots(
        1,
        2,
        figsize=(FIGURE_WIDTH_IN, ROW_HEIGHT_IN * len(rows) + 2.2),
        gridspec_kw={"width_ratios": (1.55, 1.0), "wspace": 0.34},
    )
    draw_lengths(left, rows)
    draw_band_rates(right, bands)
    left.set_yticks(list(range(len(rows)))[::-1], [r.row for r in rows], fontsize=9.5)
    for axes, count in ((left, len(rows)), (right, len(bands))):
        axes.set_ylim(-0.7, count - 0.3)
        axes.grid(axis="x", color="#ececec", linewidth=0.8)
        axes.set_axisbelow(True)
        axes.tick_params(axis="y", length=0)
        for spine in ("top", "right", "left"):
            axes.spines[spine].set_visible(False)
    figure.subplots_adjust(left=0.24, right=0.95)
    frame_figure(
        figure,
        f"The prompts that stop {short_model(model)} answering odd also stop it thinking,\n"
        "and on their own the long rollouts are the ones that answer odd",
        "",
        plot_in=ROW_HEIGHT_IN * len(rows) + 0.9,
        title_in=0.75,
    )
    return figure


def build_length_confound_figure(results_dir: Path, model: str, out: Path) -> Path:
    """Read the results, draw both panels, write the file, return where it went."""
    from odd_number.traces import load_traces

    traces = load_traces(results_dir)
    rows = length_confounds(traces, sampling_by_file(results_dir), model)
    if not rows:
        raise ValueError(f"no conflict-arm rollouts for {model} in {results_dir}")
    figure = length_confound_figure(rows, band_rates(traces, model), model)
    out.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(out, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(figure)
    return out
