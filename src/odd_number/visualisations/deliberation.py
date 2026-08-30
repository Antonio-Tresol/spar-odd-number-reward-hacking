"""How long each trace thought, split by whether its answer was odd.

The question this answers is whether the odd answers come out of longer
deliberation than the even ones. It is the per-trace view behind the aggregate in
`figures`: one dot per rollout rather than one dot per model.

The axis is square-rooted, as the explainer page's strip chart is, because the
reasoning lengths span two orders of magnitude and a linear axis puts most of the
traces in the leftmost tenth. Square root spreads the short ones without the
compression at the top that a log axis would bring, and it keeps zero on the axis.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from odd_number.traces import Trace
from odd_number.visualisations.figures import (
    CAPTION_INK,
    CONFLICT_ARM,
    apply_house_style,
    is_base_cell,
    short_model,
)

#: Teal for an even answer, magenta for an odd one, as the explainer colours them.
EVEN_INK: str = "#3f7f79"
ODD_INK: str = "#c2185b"

#: Rows inside one model's panel. Odd on top, because it is the row the reader is
#: there for.
ODD_ROW: float = 1.0
EVEN_ROW: float = 0.0

#: Characters per subtitle line, sized against the figure width at 11 point.
SUBTITLE_WRAP: int = 112


@dataclass(frozen=True, slots=True)
class Deliberation:
    """One model's traces, split by the parity of the answer they ended on."""

    model: str
    odd: tuple[int, ...]
    even: tuple[int, ...]

    @property
    def shortest_odd(self) -> int | None:
        """The least reasoning that still produced an odd answer, if any did.

        The figure draws this as a guide. It is the claim a reader takes away: an
        odd answer never came out of a short deliberation, or it sometimes did.
        """
        return min(self.odd) if self.odd else None

    @property
    def longest(self) -> int:
        return max([*self.odd, *self.even], default=1)


def deliberation_of(traces: list[Trace], model: str, treatment: str = CONFLICT_ARM) -> Deliberation:
    """Reasoning lengths for one model in one arm, split by answer parity.

    Reasoning only. `Trace.chars` adds the response, which is a handful of
    characters for an answer like `42` but is not reasoning, and the axis here says
    reasoning. Traces whose answer could not be read are left out rather than
    counted as even.
    """
    chosen = [t for t in traces if is_base_cell(t, treatment) and t.model == model]
    return Deliberation(
        model=model,
        odd=tuple(sorted(len(t.reasoning) for t in chosen if t.parity == "odd")),
        even=tuple(sorted(len(t.reasoning) for t in chosen if t.parity == "even")),
    )


def draw_panel(axes: Axes, panel: Deliberation, limit: int, name_it: bool = True) -> None:
    """One model: two rows of dots, and the guide at its shortest odd trace.

    `name_it` is off when only one model is drawn, because the subtitle already names
    it and a panel heading under the subtitle reads as a second title.
    """
    for values, row, ink in ((panel.odd, ODD_ROW, ODD_INK), (panel.even, EVEN_ROW, EVEN_INK)):
        axes.scatter(
            values,
            [row] * len(values),
            s=110,
            color=ink,
            alpha=0.75,
            edgecolors="none",
            zorder=3,
        )
    if panel.shortest_odd is not None:
        axes.axvline(panel.shortest_odd, color=ODD_INK, linestyle=(0, (4, 4)), linewidth=1.2)
        axes.annotate(
            f"{panel.shortest_odd:,}, the shortest odd one",
            xy=(panel.shortest_odd, ODD_ROW + 0.55),
            xytext=(7, 0),
            textcoords="offset points",
            ha="left",
            va="center",
            size=10,
            color=ODD_INK,
        )
    axes.set_yticks(
        [ODD_ROW, EVEN_ROW],
        [f"answered odd\n{len(panel.odd)}", f"answered even\n{len(panel.even)}"],
    )
    for tick, ink in zip(axes.get_yticklabels(), (ODD_INK, EVEN_INK), strict=True):
        tick.set_color(ink)
        tick.set_fontweight("bold")
    axes.set_ylim(-0.75, ODD_ROW + 0.95)
    axes.set_xlim(0, limit * 1.06)
    if name_it:
        axes.set_title(short_model(panel.model), loc="left", size=12, fontweight="bold", pad=6)
    axes.grid(axis="x", color="#eceded", linewidth=0.8)
    axes.set_axisbelow(True)
    for side in ("top", "right", "left"):
        axes.spines[side].set_visible(False)
    axes.spines["bottom"].set_color("#d1d5db")
    axes.tick_params(axis="y", length=0)


def deliberation_figure(panels: list[Deliberation]) -> Figure:
    """One panel per model, on one shared square-root axis.

    Shared on purpose. Two panels scaled independently would look alike while
    meaning different things, and the comparison a reader wants is exactly whether
    one model deliberates longer than the other.
    """
    apply_house_style()
    limit = max(p.longest for p in panels)
    solo = len(panels) == 1
    figure, axes = plt.subplots(
        len(panels), 1, figsize=(10.4, 2.9 * len(panels) + 2.0), dpi=140, sharex=True
    )
    figure.subplots_adjust(
        left=0.19,
        right=0.97,
        top=0.76 if solo else 0.83,
        bottom=0.20 if solo else 0.16,
        hspace=0.42,
    )
    for panel, ax in zip(panels, np.atleast_1d(axes), strict=True):
        draw_panel(ax, panel, limit, name_it=not solo)

    last = np.atleast_1d(axes)[-1]
    # Square root, not log: the lengths span two orders of magnitude, and a linear
    # axis buries most traces in the leftmost tenth. Ticks are placed by hand at the
    # quarters of the root so the labels stay round instead of landing on 3,162.
    last.set_xscale("function", functions=(np.sqrt, np.square))
    last.set_xticks([0, limit // 16, limit // 4, limit])
    last.set_xticklabels([tick_label(v) for v in (0, limit // 16, limit // 4, limit)])
    last.set_xlabel("Characters of reasoning before the answer", labelpad=8)

    who = f" of {short_model(panels[0].model)}" if solo else ""
    figure.text(
        0.035,
        0.965,
        "Does an odd answer come out of a longer deliberation?",
        size=15,
        weight="bold",
        color="#111827",
        va="top",
    )
    figure.text(
        0.035,
        0.905,
        # Wrapped: matplotlib draws a long line straight off the right edge.
        textwrap.fill(
            f"One dot per rollout{who}, conflict arm, verbatim wording. Square-root axis, so"
            " the short traces do not all pile up at the left.",
            SUBTITLE_WRAP,
        ),
        size=11,
        linespacing=1.5,
        color=CAPTION_INK,
        va="top",
    )
    return figure


def tick_label(value: int) -> str:
    """Round thousands for an axis: 18,432 reads as 18k."""
    return f"{round(value / 1000)}k" if value >= 1000 else str(value)
