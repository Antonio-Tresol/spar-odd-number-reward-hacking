"""Reader labels are counted over all 40 traces a model was read on.

An earlier version counted each label only against the traces it was "available"
for, because the reading agent's vocabulary drifted between groups. That was
defensible and unreadable: a label seen 3 times in a 4-trace group came out at 75%,
level with one seen 22 times in a 36-trace group. Pooling to a constant denominator
is what these tests hold in place.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from odd_number.readings import Reading  # noqa: E402
from odd_number.traces import Trace  # noqa: E402
from odd_number.visualisations.tags import (  # noqa: E402
    Batch,
    Tag,
    always_applied,
    batches_for,
    glossary_for,
    model_tags,
    plural,
    ranked_tags,
    shared_vocabulary,
    tag_bars_figure,
    traces_read,
)

FILE = "odd-number-qwen-qwen3.8-27b.jsonl"
ARM = "conflict-grader"
MODEL = "qwen/qwen3.8-27b"


def trace(index: int, model: str = MODEL, file: str = FILE) -> Trace:
    return Trace(
        file=file,
        model=model,
        treatment=ARM,
        condition="conflict",
        index=index,
        prompt="Choose a random even number.",
        reasoning="",
        response="2",
        finish_reason="stop",
        number=2,
        parity="even",
        answer_source="literal",
    )


def reading(index: int, chunk: str, labels: tuple[str, ...]) -> Reading:
    return Reading(
        file=FILE,
        treatment=ARM,
        index=index,
        chunk=chunk,
        reader="claude-sonnet-5",
        reads_grader="yes",
        grader_reading="",
        situation="",
        decision="",
        quotes=(),
        labels=labels,
        interesting=False,
        why_interesting="",
        answer_as_read=2,
    )


def corpus(spec: dict[int, tuple[str, tuple[str, ...]]]) -> tuple[list[Trace], dict]:
    traces = [trace(i) for i in spec]
    readings = {(FILE, ARM, i): reading(i, chunk, labels) for i, (chunk, labels) in spec.items()}
    return traces, readings


def test_a_label_used_in_two_groups_is_counted_once_over_both() -> None:
    """`no-disclosure` is 23 traces, not 13 in one row and 10 in another."""
    traces, readings = corpus(
        {
            0: ("c--1of2", ("both",)),
            1: ("c--1of2", ("both",)),
            2: ("c--2of2", ("both",)),
        }
    )
    group = batches_for(traces, readings, MODEL)
    (merged,) = model_tags(group)
    assert (merged.name, merged.count) == ("both", 3)
    assert traces_read(group) == 3


def test_the_denominator_is_every_trace_read_not_the_group_a_label_came_from() -> None:
    """The fix for `3 of 4` ranking level with `22 of 36`: there is one denominator."""
    traces, readings = corpus(
        {i: ("c--1of2", ("common",)) for i in range(6)} | {6: ("c--2of2", ("rare",))}
    )
    group = batches_for(traces, readings, MODEL)
    counts = {tag.name: tag.count for tag in model_tags(group)}
    assert counts == {"common": 6, "rare": 1}
    assert traces_read(group) == 7, "the rare label is 1 of 7, not 1 of 1"


def test_labels_are_ranked_by_count_and_ties_broken_so_reruns_match() -> None:
    traces, readings = corpus(
        {
            0: ("c--1of1", ("beta", "alpha", "solo")),
            1: ("c--1of1", ("beta", "alpha")),
        }
    )
    group = batches_for(traces, readings, MODEL)
    assert [tag.name for tag in ranked_tags(group)] == ["alpha", "beta", "solo"]
    assert ranked_tags(group) == ranked_tags(group)


def test_ranking_stops_at_the_limit() -> None:
    group = [Batch("m", "c--1of1", 20, tuple(Tag(f"t{i}", i + 1) for i in range(15)))]
    assert len(ranked_tags(group, limit=5)) == 5


def test_a_trace_with_no_reading_is_left_out_rather_than_counted_as_untagged() -> None:
    traces = [trace(0), trace(1)]
    readings = {(FILE, ARM, 0): reading(0, "c--1of1", ("alpha",))}
    group = batches_for(traces, readings, MODEL)
    assert traces_read(group) == 1, "an unread trace must not inflate the denominator"


def test_a_label_that_never_failed_to_apply_is_reported_but_not_drawn() -> None:
    """It describes the run rather than any trace, which the notebook says in words."""
    group = [
        Batch("m", "c--1of2", 13, (Tag("everywhere", 13), Tag("sometimes", 4))),
        Batch("m", "c--2of2", 10, (Tag("everywhere", 10),)),
    ]
    assert always_applied(group) == ["everywhere"]


def test_a_group_of_one_trace_cannot_make_a_label_look_universal() -> None:
    """1 of 1 is not evidence that a label always applies."""
    assert always_applied([Batch("m", "c--1of1", 1, (Tag("lonely", 1),))]) == []


def test_shared_vocabulary_is_what_makes_reading_across_models_meaningful() -> None:
    left = [Batch("m", "c--1of1", 2, (Tag("a", 1), Tag("b", 1)))]
    right = [Batch("n", "d--1of1", 2, (Tag("b", 1), Tag("c", 1)))]
    assert shared_vocabulary(left, right) == {"b"}
    assert shared_vocabulary(left, [Batch("n", "d--1of1", 1, (Tag("z", 1),))]) == set()


def test_a_glossary_returns_the_readings_that_used_a_label() -> None:
    """No label is defined anywhere, so its meaning is only what these notes say."""
    traces, readings = corpus(
        {
            0: ("c--1of1", ("wanted",)),
            1: ("c--1of1", ("other",)),
            2: ("c--1of1", ("wanted",)),
        }
    )
    found = glossary_for(traces, readings, MODEL, "wanted")
    assert [r.index for r in found] == [0, 2]
    assert glossary_for(traces, readings, MODEL, "never-used") == []


def test_plural_agrees_with_its_count() -> None:
    assert plural(1, "label") == "1 label"
    assert plural(0, "label") == "0 labels"


def test_the_figure_labels_its_own_denominator_and_refuses_the_comparison() -> None:
    left = [Batch("a/one", "c--1of1", 40, (Tag("x", 22), Tag("y", 3)))]
    right = [Batch("b/two", "d--1of1", 40, (Tag("z", 15),))]
    figure = tag_bars_figure([left, right], limit=3)
    try:
        assert len(figure.axes) == 2
        # Wrapping inserts newlines, so assert on phrases that survive a line break.
        drawn = " ".join(t.get_text() for t in figure.texts)
        assert "cannot be compared" in drawn
        assert "share 0 labels" in drawn
        for axes in figure.axes:
            assert "of 40 read" in axes.get_xlabel()
        # No row carries a group id, and no bar is labelled as a share.
        rows = [t.get_text() for ax in figure.axes for t in ax.get_yticklabels()]
        assert all("batch" not in row and "%" not in row for row in rows)
        bars = [t.get_text() for ax in figure.axes for t in ax.texts]
        assert set(bars) == {"22", "3", "15"}
    finally:
        plt.close(figure)


def test_one_model_drops_the_sentence_about_comparing_panels() -> None:
    """With a single panel there is nothing to compare, so the caveat would be noise."""
    solo = tag_bars_figure([[Batch("a/one", "c--1of1", 40, (Tag("x", 22),))]], limit=2)
    try:
        drawn = " ".join(t.get_text() for t in solo.texts)
        assert "cannot be compared" not in drawn
        assert "share 0 labels" not in drawn
        # The model is named once, in the figure title, not again over the panel.
        assert "one" in drawn
        assert solo.axes[0].get_title(loc="left") == ""
    finally:
        plt.close(solo)


def test_two_models_keep_the_sentence_about_comparing_panels() -> None:
    pair = tag_bars_figure(
        [
            [Batch("a/one", "c--1of1", 40, (Tag("x", 22),))],
            [Batch("b/two", "d--1of1", 40, (Tag("z", 15),))],
        ],
        limit=2,
    )
    try:
        drawn = " ".join(t.get_text() for t in pair.texts)
        assert "cannot be compared" in drawn
        # With more than one panel each is named over its own bars.
        assert {ax.get_title(loc="left") for ax in pair.axes} == {"one", "two"}
    finally:
        plt.close(pair)
