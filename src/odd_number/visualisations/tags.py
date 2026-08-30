"""The labels an agent reader put on traces, and how often it reached for each.

Every trace was read by an agent, which wrote a note on it and attached labels. The
agent was given no fixed vocabulary and could not read all 40 traces of a model at
once, so it made up labels as it went and its wording drifted between groups.

That drift shaped an earlier version of this module, which counted each label
against only the traces it was "available" for and drew one row per label per group.
It was defensible and unreadable: a label seen 3 times in a 4-trace group came out at
75% and sat next to one seen 22 times in a 36-trace group at 61%, which is exactly
the comparison the drift makes meaningless.

Counts are now pooled over all 40 traces a model was read on. The denominator is a
real constant, `3` reads as rare instead of as 75%, and the caveat that remains is
about how to read a low count rather than about how the reading was scheduled.

What does not pool is the two models. Kimi and qwen were read by the same agent and
share no label at all, so `resists_gaming` and `rejects-gaming` are two coinages
rather than one measurement counted twice, and the figure says so.
"""

from __future__ import annotations

import textwrap
from collections import Counter, defaultdict
from dataclasses import dataclass

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from odd_number.readings import Reading, TraceKey, trace_key
from odd_number.traces import Trace
from odd_number.visualisations.figures import (
    CAPTION_INK,
    CONFLICT_ARM,
    apply_house_style,
    is_base_cell,
    short_model,
)

TAG_INK: str = "#a3325c"

#: How many labels per model the chart shows. The tail is a long list used once each,
#: which says more about how freely the agent coined labels than about the traces.
TOP_TAGS: int = 8
FIGURE_WIDTH_IN: float = 10.4
#: Characters per line of the figure's prose, sized against its width at 11 point.
SUBTITLE_WRAP: int = 118


@dataclass(frozen=True, slots=True)
class Tag:
    """One label and how many traces carried it."""

    name: str
    count: int


@dataclass(frozen=True, slots=True)
class Batch:
    """One group of traces the agent read together, and the labels it used on them."""

    model: str
    chunk: str
    traces: int
    tags: tuple[Tag, ...]


def batches_for(
    traces: list[Trace],
    readings: dict[TraceKey, Reading],
    model: str,
    treatment: str = CONFLICT_ARM,
) -> list[Batch]:
    """Every group of one model's traces the agent read, with the labels it used.

    The groups are kept rather than flattened here because two things still need
    them: `always_applied`, which asks whether a label ever failed to be applied,
    and anyone checking how the reading was scheduled.
    """
    members: dict[str, list[Reading]] = defaultdict(list)
    for trace in traces:
        if is_base_cell(trace, treatment) and trace.model == model:
            reading = readings.get(trace_key(trace))
            if reading is not None:
                members[reading.chunk].append(reading)
    batches: list[Batch] = []
    for chunk, group in sorted(members.items()):
        counts = Counter(label for reading in group for label in reading.labels)
        tags = tuple(
            Tag(name, count)
            for name, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        )
        batches.append(Batch(model, chunk, len(group), tags))
    return batches


def traces_read(group: list[Batch]) -> int:
    """How many traces the agent read for this model. The denominator for every count."""
    return sum(batch.traces for batch in group)


def model_tags(group: list[Batch]) -> list[Tag]:
    """Every label the agent used on one model, counted over all its traces."""
    counts: Counter[str] = Counter()
    for batch in group:
        for tag in batch.tags:
            counts[tag.name] += tag.count
    return [Tag(name, count) for name, count in counts.items()]


def ranked_tags(group: list[Batch], limit: int = TOP_TAGS) -> list[Tag]:
    """A model's labels, most-used first, ties broken alphabetically so reruns match."""
    tags = model_tags(group)
    tags.sort(key=lambda tag: (-tag.count, tag.name))
    return tags[:limit]


def always_applied(group: list[Batch]) -> list[str]:
    """Labels the agent put on every trace it read while that label was in use.

    Not drawn. A label that never failed to apply tells you the agent saw no
    variation to distinguish, which makes it a description of the run rather than of
    any trace in it. That is a sentence about the reading, so the notebook says it in
    words instead of the figure encoding it in a colour nobody can decode.
    """
    always = [
        tag.name
        for batch in group
        for tag in batch.tags
        if tag.count == batch.traces and batch.traces > 1
    ]
    return sorted(set(always))


def shared_vocabulary(*groups: list[Batch]) -> set[str]:
    """Labels every one of these models' readings used.

    The number that decides whether reading across the panels means anything.
    """
    vocabularies = [
        {tag.name for batch in group for tag in batch.tags} for group in groups if group
    ]
    return set.intersection(*vocabularies) if vocabularies else set()


def plural(count: int, noun: str) -> str:
    """`1 label`, `0 labels`. Computed, because the count it describes is computed."""
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def glossary_for(
    traces: list[Trace],
    readings: dict[TraceKey, Reading],
    model: str,
    tag: str,
    treatment: str = CONFLICT_ARM,
) -> list[Reading]:
    """Every reading that used this label, so its working meaning can be read off them.

    No definition of any label exists. The agent coined them as it went and never
    wrote a glossary, and none of the chunk reports so much as mentions a label
    string. What a label meant is therefore only recoverable from the notes on the
    traces it was put on, which is what this returns.
    """
    found = [
        readings[trace_key(t)]
        for t in traces
        if is_base_cell(t, treatment)
        and t.model == model
        and trace_key(t) in readings
        and tag in readings[trace_key(t)].labels
    ]
    return sorted(found, key=lambda r: r.index)


def draw_model(axes: Axes, group: list[Batch], limit: int = TOP_TAGS, name_it: bool = True) -> None:
    """One model's most-used labels as bars, most-used at the top.

    `name_it` is off when the figure draws a single model, because the figure's own
    title already names it and repeating it reads as two headings for one chart.
    """
    ranked = ranked_tags(group, limit)
    total = traces_read(group)
    positions = list(range(len(ranked)))
    axes.barh(positions, [tag.count for tag in ranked], color=TAG_INK, height=0.66, zorder=3)
    for row, tag in enumerate(ranked):
        axes.annotate(
            str(tag.count),
            xy=(tag.count, row),
            xytext=(7, 0),
            textcoords="offset points",
            va="center",
            size=10,
            color=CAPTION_INK,
        )
    axes.set_yticks(positions, [tag.name for tag in ranked])
    axes.invert_yaxis()
    axes.set_xlim(0, total * 1.12)
    axes.set_xticks([0, total // 2, total])
    if name_it:
        axes.set_title(short_model(group[0].model), loc="left", size=13, fontweight="bold", pad=10)
    axes.set_xlabel(f"traces carrying the label, of {total} read", size=10, labelpad=8)
    axes.grid(axis="x", color="#eceded", linewidth=0.8)
    axes.set_axisbelow(True)
    axes.tick_params(axis="y", length=0, labelsize=10.5)
    for side in ("top", "right", "left"):
        axes.spines[side].set_visible(False)
    axes.spines["bottom"].set_color("#d1d5db")


def tag_bars_figure(groups: list[list[Batch]], limit: int = TOP_TAGS) -> Figure:
    """The labels the agent reader used most, one panel per model given.

    Takes a list so it can draw one model or several. With one it is narrower and
    drops the sentence about comparing panels, which would be talking about a
    comparison the figure does not offer.
    """
    apply_house_style()
    solo = len(groups) == 1
    width = FIGURE_WIDTH_IN * (0.76 if solo else 1.0)
    figure, axes = plt.subplots(1, len(groups), figsize=(width, 0.40 * limit + 3.0), dpi=140)
    figure.subplots_adjust(
        left=0.30 if solo else 0.21, right=0.96, top=0.72, bottom=0.22, wspace=0.95
    )
    for group, ax in zip(groups, np.atleast_1d(axes), strict=True):
        draw_model(ax, group, limit, name_it=not solo)

    names = " and ".join(short_model(group[0].model) for group in groups if group)
    figure.text(
        0.035 if not solo else 0.045,
        0.965,
        f"What an agent reader said it saw in {names} traces",
        size=15 if not solo else 14,
        weight="bold",
        color="#111827",
        va="top",
    )
    figure.text(
        0.035 if not solo else 0.045,
        0.905,
        textwrap.fill(
            "Every trace was read by an agent, which wrote a note on it and made up its own"
            f" labels. These are the {limit} it used most" + ("." if solo else " on each model."),
            SUBTITLE_WRAP if not solo else int(SUBTITLE_WRAP * 0.76),
        ),
        size=11,
        color=CAPTION_INK,
        va="top",
        linespacing=1.5,
    )
    note = (
        "A low count can mean the label did not fit a trace, or that the agent was not yet"
        " using that wording when it read it."
    )
    if not solo:
        note += (
            f" The two models share {plural(len(shared_vocabulary(*groups)), 'label')}, so the"
            " panels cannot be compared with each other."
        )
    figure.text(
        0.035 if not solo else 0.045,
        0.085,
        textwrap.fill(note, SUBTITLE_WRAP if not solo else int(SUBTITLE_WRAP * 0.76)),
        size=9.5,
        color=CAPTION_INK,
        va="top",
        linespacing=1.5,
    )
    return figure
