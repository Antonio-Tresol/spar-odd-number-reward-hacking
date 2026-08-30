"""Figures for the report notebooks, built from the same traces the explainer reads.

One figure lives here so far: the per-model rate of answering with an odd number
when the in-context reward function rewards odd and the instruction asks for even.

The cell selection mirrors the explainer page's `base` column (`COLS[0]` in
`templates/odd-number-traces.html`): the verbatim instruction wording only, with
paraphrase, label-intervention and vendor-sampling re-runs excluded, and with the
files that are not rollouts of the environment left out. It is a second copy of
that rule in a second language, so the two are kept side by side deliberately and
`tests/test_figures.py` pins the counts the explainer shows.
"""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.ticker import MultipleLocator, PercentFormatter

from odd_number.grades import wilson_interval
from odd_number.traces import Trace

#: The arm where the reward function and the instruction disagree.
CONFLICT_ARM: str = "conflict-grader"
#: The arm where they agree, which is the control.
AGREE_ARM: str = "agree-grader"

#: Results files that are not rollouts of the environment: provider smoke tests,
#: a second endpoint for one model, and a reasoning-effort variant.
ARTEFACT_FILE = re.compile(r"no-effort|novita|ladder-smoke|deepseek-r1")
#: Re-runs that change the instruction wording, add a label to the metadata, or
#: change the sampling parameters. The base cell is the verbatim prompt only.
VARIANT_FILE = re.compile(r"-(p[1-4]|test|misaligned|want|vendor-sampling)\.jsonl$")

#: Filled for a model that answered odd at least once, hollow for one that never
#: did. The distinction carries the figure's main caveat, so it is encoded twice:
#: in the marker and in the legend text.
ODD_INK: str = "#c2185b"
CONTROL_INK: str = "#6b7280"
CAPTION_INK: str = "#4b5563"
FLOOR_BAND: str = "#eceded"

#: Where the caption sits, in figure coordinates. The body column is fixed rather
#: than measured, so the labels stay aligned instead of ragged; it is wide enough
#: for the longest label here with room to spare.
CAPTION_X: float = 0.035
CAPTION_BODY_X: float = 0.16
CAPTION_TOP: float = 0.265
#: One wrapped line, and the gap between one row and the next.
CAPTION_LINE: float = 0.030
CAPTION_GAP: float = 0.016
#: Characters per caption line. Matplotlib does not wrap text, so a sentence longer
#: than the figure is drawn straight off the edge rather than flowing. Wrapping is
#: by character count, which is close enough at a fixed font size and cannot fail
#: the way measuring the rendered width can.
CAPTION_WRAP: int = 118

#: The count sits this far above its dot, in row units, and this many points to its
#: right. Right rather than left: a model at 0 percent sits on the control line, and
#: a label nudged left would be drawn straight through it.
LABEL_LIFT: float = 0.30
LABEL_NUDGE: float = 9.0


@dataclass(frozen=True, slots=True)
class GamingRate:
    """How often one model answered odd in one arm, with its uncertainty."""

    model: str
    odd: int
    parseable: int
    ci_low: float
    ci_high: float

    @property
    def rate(self) -> float:
        """Share of parseable answers that were odd, as a fraction."""
        return self.odd / self.parseable if self.parseable else 0.0

    @property
    def ever(self) -> bool:
        """Whether this model produced an odd answer at all."""
        return self.odd > 0


#: Open Sans, vendored under OFL-1.1 with its licence beside it. It is here rather
#: than named as a system font because `figures/` is committed and the notes cite
#: those images: a font the repository cannot carry would render correctly on one
#: machine and silently fall back to DejaVu Sans on every other. It is also on
#: Google Fonts, so a write-up can use the same face.
FONT_DIR: Path = Path(__file__).resolve().parents[3] / "assets" / "fonts"
FONT_FAMILY: str = "Open Sans"
#: Tried in order. The last is bundled with matplotlib, so text always renders.
FONT_STACK: tuple[str, ...] = (FONT_FAMILY, "Liberation Sans", "Arial", "DejaVu Sans")


def apply_house_style() -> None:
    """Register the vendored fonts and point matplotlib at them.

    Called by each figure builder rather than at import, because this package's
    modules are library code and mutating global `rcParams` on import would change
    the look of any other matplotlib figure in the same process.

    Missing font files are not an error: the stack falls through to the face
    matplotlib ships, so a checkout without `assets/fonts` still draws.
    """
    for path in sorted(FONT_DIR.glob("*.ttf")):
        font_manager.fontManager.addfont(str(path))
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = [*FONT_STACK, *plt.rcParams["font.sans-serif"]]
    plt.rcParams["axes.unicode_minus"] = False


def is_base_cell(trace: Trace, treatment: str) -> bool:
    """Whether a trace belongs to the verbatim-wording cell of one arm."""
    return (
        trace.treatment == treatment
        and not ARTEFACT_FILE.search(trace.file)
        and not VARIANT_FILE.search(trace.file)
    )


def arm_prompt(traces: list[Trace], treatment: str) -> str:
    """The prompt sent in one arm, read back from the rollouts themselves.

    Read rather than retyped so a notebook can show the exact bytes the models
    saw. Every rollout in a cell carries the same prompt.

    Raises:
        LookupError: when no rollout of that arm is in the corpus, which means
            the results directory is not the one this figure describes.
    """
    prompts = {t.prompt for t in traces if is_base_cell(t, treatment)}
    if not prompts:
        raise LookupError(f"no verbatim-wording rollouts for {treatment!r}")
    if len(prompts) > 1:
        raise LookupError(f"{treatment!r} rollouts disagree on the prompt: {len(prompts)} variants")
    return prompts.pop()


def gaming_rates(traces: list[Trace], treatment: str) -> list[GamingRate]:
    """Per-model odd-answer rates for one arm, highest first.

    Unparseable answers are dropped from the denominator rather than counted as
    even, so the rate is over answers that were actually read as a number.
    """
    members: dict[str, list[Trace]] = {}
    for trace in traces:
        if is_base_cell(trace, treatment):
            members.setdefault(trace.model, []).append(trace)
    rates: list[GamingRate] = []
    for model, group in members.items():
        parseable = [t for t in group if t.parity in ("odd", "even")]
        odd = sum(1 for t in parseable if t.parity == "odd")
        low, high = wilson_interval(odd, len(parseable))
        rates.append(GamingRate(model, odd, len(parseable), low, high))
    return sorted(rates, key=lambda r: (-r.rate, r.model))


def resolution_floor(rates: list[GamingRate]) -> float:
    """The highest rate a model that never gamed could still have, at this n.

    A model observed at 0 of 40 has a 95% Wilson interval reaching about 9%. That
    number, not zero, is what "never happened" is worth here, and the figure
    draws it as a band so the reader is not invited to read a zero as an absence.
    """
    never = [r for r in rates if not r.ever]
    return max((r.ci_high for r in never), default=0.0)


def figure_verdict(rates: list[GamingRate]) -> str:
    """The figure's own answer to its title question, computed from the data.

    Deliberately two clauses. Counting models that ever gamed overstates the
    result, because two of them did it once and their intervals reach down to
    almost zero. Counting only models that clear the floor understates it, since
    a single odd answer is still an odd answer. The title says both.
    """
    floor = resolution_floor(rates)
    ever = [r for r in rates if r.ever]
    clear = [r for r in ever if r.ci_low > floor]
    names = ", ".join(short_model(r.model) for r in clear) or "none"
    verb = "clears" if len(clear) == 1 else "clear"
    return (
        f"{len(ever)} of {len(rates)} did at least once, "
        f"but only {names} {verb} the {floor:.0%} that {rates[0].parseable} rollouts can resolve"
    )


def short_model(model: str) -> str:
    """The part of a slug a person says out loud: `qwen/qwen3.8-27b` to `qwen3.8-27b`."""
    return model.split("/", 1)[-1]


def control_summary(rates: list[GamingRate]) -> str:
    """The control arm in one clause, counted rather than asserted.

    Drawn as a single annotated line rather than one marker per model. Every model
    sits at exactly zero there, so nine markers would land on top of each other and
    on the hollow dots of the five models that never gamed. The notebook prints the
    per-model control counts beside the figure for anyone who wants to check.
    """
    odd = sum(r.odd for r in rates)
    seen = sum(r.parseable for r in rates)
    return f"{odd} of {seen} across all {len(rates)} models"


def caption_rows(conflict: list[GamingRate], agree: list[GamingRate]) -> list[tuple[str, str]]:
    """The notes that go under the plot, as (label, sentence) pairs.

    A definition list rather than prose with bold lead-ins, because matplotlib has
    no inline rich text: a run of bold inside a sentence would have to be measured
    and positioned by hand at a given DPI. Two aligned columns say the same thing
    and survive a resize.

    Each row is one thing a reader could otherwise get wrong.
    """
    n = conflict[0].parseable
    floor = resolution_floor(conflict)
    return [
        (
            "One dot",
            f"is one model: the share of its {n} rollouts whose final answer was odd. "
            "Bars are 95% Wilson intervals.",
        ),
        (
            "Chance",
            "is not 50 percent. A model that follows the instruction answers even every "
            "time, so the floor is 0 percent.",
        ),
        (
            "Shaded band",
            f"ends at {floor:.0%}, the top of the interval for a model seen at 0 of {n}. "
            "Rates inside it are consistent with never gaming.",
        ),
        (
            "Grey line",
            "is the control arm, where reward and instruction agree. There, "
            f"{control_summary(agree)} answered odd.",
        ),
    ]


def legend_marker(ever: bool) -> dict[str, object]:
    """The dot on its own, with no line and no error bar, for a legend handle.

    Shared with `draw_rates` so the key cannot end up showing a different marker
    from the plot, which is the usual way a hand-built legend goes wrong.
    """
    return {
        "marker": "o",
        "linestyle": "none",
        "markersize": 9,
        "markerfacecolor": ODD_INK if ever else "white",
        "markeredgecolor": ODD_INK,
        "markeredgewidth": 1.8,
    }


def draw_rates(axes: Axes, rates: list[GamingRate], ever: bool) -> None:
    """One dot-and-interval series: filled for models that gamed, hollow for those that never did.

    Split into two series rather than one with mixed colours so the legend can name
    what hollow means. "Never observed" is the reading most likely to be taken as
    "never happens", so it gets its own entry rather than a footnote.
    """
    chosen = [r for r in rates if r.ever is ever]
    if not chosen:
        return
    axes.errorbar(
        [r.rate for r in chosen],
        [rates.index(r) for r in chosen],
        xerr=[
            [r.rate - r.ci_low for r in chosen],
            [r.ci_high - r.rate for r in chosen],
        ],
        ecolor=ODD_INK,
        elinewidth=1.3,
        capsize=4,
        capthick=1.3,
        zorder=3,
        **legend_marker(ever),
    )
    # The count, not the percentage. A reader who can see "1 of 40" is not going to
    # mistake it for a rate estimated from a lot of data, which "2.5%" invites.
    #
    # Above the dot rather than beside it: the interval runs horizontally through
    # every dot, and the row above is empty, so this is the one direction with
    # nothing in it at any rate.
    for rate in chosen:
        axes.annotate(
            f"{rate.odd} of {rate.parseable}",
            xy=(rate.rate, rates.index(rate) - LABEL_LIFT),
            ha="left",
            va="center",
            xytext=(LABEL_NUDGE, 0),
            textcoords="offset points",
            size=9,
            color=ODD_INK if ever else CAPTION_INK,
            zorder=4,
        )


def draw_caption(figure: Figure, rows: list[tuple[str, str]]) -> None:
    """The definition list under the plot, in figure coordinates.

    Placed in figure rather than axes coordinates so it is anchored to the page and
    not to the data area, and so `subplots_adjust` reserves room for it rather than
    the text landing on the legend.

    Rows advance by their own wrapped height rather than a fixed step, so a sentence
    that grows to two lines pushes the rows under it down instead of sitting on top
    of them.
    """
    y = CAPTION_TOP
    for label, sentence in rows:
        wrapped = textwrap.fill(sentence, CAPTION_WRAP)
        figure.text(CAPTION_X, y, label, size=9.5, weight="bold", color=CAPTION_INK, va="top")
        figure.text(
            CAPTION_BODY_X, y, wrapped, size=9.5, color=CAPTION_INK, va="top", linespacing=1.5
        )
        y -= (wrapped.count("\n") + 1) * CAPTION_LINE + CAPTION_GAP


def gaming_rate_figure(conflict: list[GamingRate], agree: list[GamingRate]) -> Figure:
    """The per-model gaming-rate figure, titled with its own verdict.

    Every number in the title and the caption is computed from the two rate lists,
    so the figure cannot disagree with the data behind it.
    """
    apply_house_style()
    n = conflict[0].parseable
    floor = resolution_floor(conflict)
    figure, axes = plt.subplots(figsize=(10.4, 8.0), dpi=140)
    figure.subplots_adjust(left=0.20, right=0.975, top=0.82, bottom=0.42)

    axes.axvspan(0, floor, color=FLOOR_BAND, zorder=0)
    axes.axvline(0, color=CONTROL_INK, linewidth=1.4, zorder=1)
    draw_rates(axes, conflict, True)
    draw_rates(axes, conflict, False)

    axes.set_yticks(range(len(conflict)), [short_model(r.model) for r in conflict])
    # Explicit limits rather than the default margins: the count labels sit above
    # their dots, so the top row needs headroom or its label lands on the band
    # annotation outside the axes.
    axes.set_ylim(len(conflict) - 0.4, -0.85)
    axes.set_xlim(-0.012, 0.44)
    axes.xaxis.set_major_formatter(PercentFormatter(xmax=1, decimals=0))
    axes.xaxis.set_major_locator(MultipleLocator(0.05))
    axes.set_xlabel(
        f"Share of rollouts whose final answer was an odd number (percent of n={n} per model)",
        labelpad=10,
    )
    axes.set_ylabel("Model", labelpad=10)
    axes.grid(axis="x", color="#e5e7eb", linewidth=0.8, zorder=0)
    axes.set_axisbelow(True)
    for side in ("top", "right", "left"):
        axes.spines[side].set_visible(False)
    axes.spines["bottom"].set_color("#d1d5db")
    axes.annotate(
        f"shaded band, left: any rate in here is consistent with 0 of {n}",
        xy=(floor + 0.006, 1.01),
        xycoords=("data", "axes fraction"),
        size=9.5,
        color=CAPTION_INK,
    )
    # Explicit handles: the one matplotlib builds from an errorbar puts the cap
    # marks around the dot, which reads as a different shape rather than the same
    # dot the plot uses.
    axes.legend(
        handles=[
            Line2D([], [], **legend_marker(True), label=f"answered odd at least once (of {n})"),
            Line2D([], [], **legend_marker(False), label=f"never answered odd (0 of {n})"),
        ],
        loc="upper left",
        bbox_to_anchor=(0.0, -0.19),
        ncols=2,
        frameon=False,
        fontsize=10,
        handletextpad=0.5,
    )

    figure.text(
        CAPTION_X,
        0.975,
        "Which models answer with an odd number when the reward function\n"
        "rewards odd and the instruction asks for even?",
        size=15,
        weight="bold",
        color="#111827",
        va="top",
    )
    figure.text(CAPTION_X, 0.878, figure_verdict(conflict), size=11.5, color="#111827", va="top")
    draw_caption(figure, caption_rows(conflict, agree))
    return figure
