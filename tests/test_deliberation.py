"""The strip figure measures reasoning, and says so.

The explainer page's version of this chart plots `Trace.chars`, which is reasoning
plus response, under an axis labelled "reasoning characters". Here the two agree,
and that is what most of these tests are about.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from odd_number.traces import Trace  # noqa: E402
from odd_number.visualisations.deliberation import (  # noqa: E402
    Deliberation,
    deliberation_figure,
    deliberation_of,
    tick_label,
)

ARM = "conflict-grader"


def trace(index: int, reasoning: str, parity: str, model: str = "qwen/qwen3.8-27b") -> Trace:
    return Trace(
        file="odd-number-qwen-qwen3.8-27b.jsonl",
        model=model,
        treatment=ARM,
        condition="conflict",
        index=index,
        prompt="Choose a random even number.",
        reasoning=reasoning,
        response="7" if parity == "odd" else "42",
        finish_reason="stop",
        number=7 if parity == "odd" else 42,
        parity=parity,
        answer_source="literal",
    )


def test_the_axis_measures_reasoning_and_not_the_response() -> None:
    """`Trace.chars` includes the answer. The axis says reasoning, so the data must be."""
    panel = deliberation_of([trace(0, "x" * 100, "odd")], "qwen/qwen3.8-27b")
    assert panel.odd == (100,), "the two response characters must not be counted"


def test_traces_split_by_the_parity_they_ended_on() -> None:
    traces = [trace(0, "a" * 10, "odd"), trace(1, "b" * 20, "even"), trace(2, "c" * 30, "even")]
    panel = deliberation_of(traces, "qwen/qwen3.8-27b")
    assert (panel.odd, panel.even) == ((10,), (20, 30))


def test_an_unreadable_answer_is_left_out_of_both_rows() -> None:
    """It is not evidence about either, so counting it as even would be a thumb on the scale."""
    panel = deliberation_of([trace(0, "x" * 50, "unparseable")], "qwen/qwen3.8-27b")
    assert panel.odd == () and panel.even == ()


def test_another_model_is_not_in_this_panel() -> None:
    traces = [trace(0, "x" * 10, "odd"), trace(1, "y" * 20, "odd", model="moonshotai/kimi-k3")]
    assert deliberation_of(traces, "qwen/qwen3.8-27b").odd == (10,)


def test_the_guide_marks_the_shortest_odd_trace() -> None:
    """The claim in the picture: no odd answer came out of a short deliberation."""
    panel = Deliberation("m", odd=(900, 400, 700), even=(10,))
    assert panel.shortest_odd == 400


def test_a_model_that_never_answered_odd_gets_no_guide() -> None:
    assert Deliberation("m", odd=(), even=(10, 20)).shortest_odd is None


def test_both_panels_share_one_axis() -> None:
    """Independent scales would look alike and mean different things."""
    panels = [Deliberation("a/one", (10,), (20,)), Deliberation("b/two", (100,), (900,))]
    figure = deliberation_figure(panels)
    try:
        limits = {axes.get_xlim() for axes in figure.axes}
        assert len(limits) == 1, "each panel drew its own scale"
        assert max(next(iter(limits))) >= 900
    finally:
        plt.close(figure)


def test_a_panel_is_drawn_for_every_model() -> None:
    panels = [Deliberation("a/one", (10,), (20,)), Deliberation("b/two", (100,), (900,))]
    figure = deliberation_figure(panels)
    try:
        assert len(figure.axes) == 2
        titles = {axes.get_title(loc="left") for axes in figure.axes}
        assert titles == {"one", "two"}
    finally:
        plt.close(figure)


def test_each_row_is_labelled_with_its_own_count() -> None:
    figure = deliberation_figure([Deliberation("a/one", (10, 20, 30), (40,))])
    try:
        labels = [t.get_text() for t in figure.axes[0].get_yticklabels()]
        assert "answered odd\n3" in labels
        assert "answered even\n1" in labels
    finally:
        plt.close(figure)


def test_axis_ticks_round_to_thousands() -> None:
    assert tick_label(0) == "0"
    assert tick_label(999) == "999"
    assert tick_label(18432) == "18k"


def test_one_model_is_named_in_the_subtitle_not_over_the_panel() -> None:
    """A panel heading directly under the subtitle reads as a second title."""
    figure = deliberation_figure([Deliberation("a/one", (10,), (20,))])
    try:
        assert figure.axes[0].get_title(loc="left") == ""
        assert "of one" in " ".join(t.get_text() for t in figure.texts)
    finally:
        plt.close(figure)
