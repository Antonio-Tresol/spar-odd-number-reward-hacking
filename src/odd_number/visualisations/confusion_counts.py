"""How often each confusion appears, and how often those traces answered odd.

Two panels because the two numbers answer different questions and share only a
row. The left one is prevalence: how much of the corpus raises this at all. The
right one is composition: of the traces that raise it, what share went on to
answer odd, read against the corpus base rate rather than against zero.

The base rate line is the point of the right panel. Every category sits well
above zero on it, so without the line a reader would conclude all six predict
gaming. Against 12% only one of them clearly does.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.ticker import PercentFormatter

from odd_number.confusions import QUESTIONS, is_grounded, read_labels
from odd_number.grades import wilson_interval
from odd_number.traces import Trace
from odd_number.visualisations.figures import ARTEFACT_FILE, CAPTION_INK

ALL_INK: Final[str] = "#c9c4bd"
ODD_INK: Final[str] = "#a3325c"
BASE_INK: Final[str] = "#4b5563"
FIGURE_WIDTH_IN: Final[float] = 12.6
ROW_HEIGHT_IN: Final[float] = 0.78
LABEL_WRAP: Final[int] = 34


@dataclass(frozen=True, slots=True)
class ConfusionCount:
    """One question: how many traces raise it, and how many of those answered odd."""

    question: str
    traces: int
    odd: int

    @property
    def odd_share(self) -> float:
        return self.odd / self.traces if self.traces else 0.0

    @property
    def odd_interval(self) -> tuple[float, float]:
        return wilson_interval(self.odd, self.traces)


def confusion_counts(
    traces: list[Trace], labels: dict[str, dict[str, object]]
) -> list[ConfusionCount]:
    """One `ConfusionCount` per question, over the traces that carry a label."""
    read = [t for t in traces if t.id in labels]
    counts = []
    for key, question in QUESTIONS.items():
        seen = [t for t in read if is_grounded(labels[t.id], key)]
        counts.append(
            ConfusionCount(
                question=question,
                traces=len(seen),
                odd=sum(1 for t in seen if t.parity == "odd"),
            )
        )
    return counts


def draw_prevalence(axes: Axes, counts: list[ConfusionCount], total: int) -> None:
    """Left panel: how much of the corpus raises each question, odd shown inside."""
    positions = list(range(len(counts)))[::-1]
    axes.barh(positions, [c.traces for c in counts], color=ALL_INK, height=0.62, zorder=2)
    axes.barh(positions, [c.odd for c in counts], color=ODD_INK, height=0.62, zorder=3)
    for position, count in zip(positions, counts, strict=True):
        axes.annotate(
            f"{count.traces} of {total}  ({count.traces / total:.0%})",
            xy=(count.traces, position),
            xytext=(6, 0),
            textcoords="offset points",
            va="center",
            fontsize=9.5,
            color=CAPTION_INK,
        )
    axes.set_xlim(0, total * 1.28)
    axes.set_title("How many traces raise it", fontsize=10.5, loc="left", pad=12)
    axes.set_xlabel("traces", fontsize=9.5, color=CAPTION_INK)


def draw_odd_share(axes: Axes, counts: list[ConfusionCount], base_rate: float) -> None:
    """Right panel: the odd share within each question, against the corpus base rate."""
    positions = list(range(len(counts)))[::-1]
    for position, count in zip(positions, counts, strict=True):
        low, high = count.odd_interval
        axes.plot(
            [low, high],
            [position, position],
            color=ODD_INK,
            linewidth=1.6,
            alpha=0.5,
            solid_capstyle="round",
            zorder=2,
        )
        axes.plot(
            [count.odd_share], [position], marker="o", markersize=8.5, color=ODD_INK, zorder=3
        )
        axes.annotate(
            f"{count.odd}/{count.traces}",
            xy=(high, position),
            xytext=(8, 0),
            textcoords="offset points",
            va="center",
            fontsize=9,
            color=CAPTION_INK,
        )
    axes.axvline(base_rate, color=BASE_INK, linewidth=1.3, linestyle=(0, (4, 3)), zorder=1)
    axes.annotate(
        f"corpus base rate, {base_rate:.0%}",
        xy=(base_rate, len(counts) - 0.45),
        xytext=(5, 0),
        textcoords="offset points",
        fontsize=9,
        color=BASE_INK,
    )
    axes.set_xlim(0, max(0.55, max(c.odd_interval[1] for c in counts) + 0.08))
    axes.xaxis.set_major_formatter(PercentFormatter(xmax=1.0))
    axes.set_title("Of those, how many answered odd", fontsize=10.5, loc="left", pad=12)
    axes.set_xlabel(
        "share answering odd, with 95% Wilson interval", fontsize=9.5, color=CAPTION_INK
    )


def confusion_counts_figure(counts: list[ConfusionCount], total: int, odd_total: int) -> Figure:
    """Both panels, sharing one set of row labels down the left."""
    base_rate = odd_total / total if total else 0.0
    # Header space is reserved in inches and converted, because the caption is
    # figure-level text that tight_layout cannot see and savefig's tight bbox
    # would otherwise crop the reservation away.
    header_in = 1.55
    height = header_in + 0.35 + ROW_HEIGHT_IN * len(counts)
    figure, (left, right) = plt.subplots(
        1,
        2,
        figsize=(FIGURE_WIDTH_IN, height),
        gridspec_kw={"width_ratios": (1.15, 1.0), "wspace": 0.30},
    )
    draw_prevalence(left, counts, total)
    draw_odd_share(right, counts, base_rate)

    labels = ["\n".join(textwrap.wrap(c.question, LABEL_WRAP)) for c in counts]
    left.set_yticks(list(range(len(counts)))[::-1])
    left.set_yticklabels(labels, fontsize=9.5)
    right.set_yticks(list(range(len(counts))))
    right.set_yticklabels([])
    for axes in (left, right):
        axes.set_ylim(-0.7, len(counts) - 0.3)
        axes.grid(axis="x", color="#ececec", linewidth=0.8)
        axes.set_axisbelow(True)
        axes.tick_params(axis="y", length=0)
        for spine in ("top", "right", "left"):
            axes.spines[spine].set_visible(False)

    figure.subplots_adjust(top=1 - header_in / height, bottom=0.11, left=0.20, right=0.97)
    figure.text(
        0.012,
        1 - 0.34 / height,
        "What qwen3.8-27b is unsure about under the conflicting grader",
        ha="left",
        va="top",
        fontsize=13.5,
        fontweight="bold",
    )
    figure.text(
        0.012,
        1 - 0.66 / height,
        chr(10).join(
            textwrap.wrap(
                f"Conflict arm only, {total} labelled traces of which {odd_total} answered odd. "
                "One agent read each trace and answered the six questions independently, "
                "quoting the passage that decided each yes; a label whose quote is not in the "
                "trace is not counted. A trace can raise any number of the six, so the bars do "
                "not sum to the corpus.",
                118,
            )
        ),
        ha="left",
        va="top",
        fontsize=9.5,
        color=CAPTION_INK,
    )
    return figure


def build_confusion_figure(traces: list[Trace], labels_path: Path, out: Path) -> Path:
    """Read the labels, draw both panels, write the file, return where it went."""
    pool = [
        t
        for t in traces
        if t.condition == "conflict"
        and not ARTEFACT_FILE.search(t.file)
        and t.parity in ("odd", "even")
    ]
    labels = read_labels(labels_path)
    if not labels:
        raise ValueError(f"no labels at {labels_path}; run the labelling pass first")
    read = [t for t in pool if t.id in labels]
    counts = confusion_counts(pool, labels)
    figure = confusion_counts_figure(counts, len(read), sum(1 for t in read if t.parity == "odd"))
    out.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(out, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(figure)
    return out
