"""Tests for the clarity-review checks.

The rule these hold to is the same one every check in this project follows:
a complaint must be about a fact, never about taste. So the tests come in two
halves — findings that must fire because something is objectively wrong with
the review record, and silence that must hold because the alternative is a
checker that cries wolf. The stale-review case is the important one: an honest
edit must not turn a review into a screenful of errors about excerpts that
were verbatim when the reader wrote them.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from research_graph_review import (
    load_review,
    record_waiver,
    review_report,
    slug_for,
)

DOCUMENT = """# Research tree

- Q1: Does the plain-language rule survive contact with a real project? [open]
  - Q1.H1: Agents copy the style of whatever they are editing [open]
"""

PROTOCOL = (
    "Read this document as a researcher who knows the field but has never "
    "opened this repository, and report what you cannot follow."
)


def build(tmp_path: Path, review: dict | None, document: str = DOCUMENT) -> Path:
    (tmp_path / "TREE.md").write_text(document, encoding="utf-8")
    if review is not None:
        directory = tmp_path / "reviews"
        directory.mkdir(exist_ok=True)
        (directory / "tree-md.json").write_text(json.dumps(review), encoding="utf-8")
    return tmp_path


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def good_review(document: str = DOCUMENT) -> dict:
    return {
        "artifact": "TREE.md",
        "sha256": digest(document),
        "protocol": PROTOCOL,
        "runs": [
            {
                "reader": "sonnet",
                "at": "2026-08-24",
                "verdict": "needs-work",
                "findings": [
                    {
                        "excerpt": "Agents copy the style of whatever they are editing",
                        "problem": "Cannot tell whether this is a claim or a hypothesis.",
                    }
                ],
            }
        ],
    }


def errors(findings: list[str]) -> list[str]:
    return [f for f in findings if f.startswith("ERROR")]


def test_a_review_whose_quotes_resolve_raises_nothing(tmp_path: Path) -> None:
    root = build(tmp_path, good_review())
    assert review_report(root) == []


def test_a_quote_that_is_not_in_the_document_is_an_error(tmp_path: Path) -> None:
    review = good_review()
    review["runs"][0]["findings"][0]["excerpt"] = "a sentence the reader invented wholesale"
    root = build(tmp_path, review)
    hits = errors(review_report(root))
    assert len(hits) == 1
    assert "indistinguishable from an invented one" in hits[0]


def test_a_stale_review_reports_staleness_and_never_its_quotes(tmp_path: Path) -> None:
    """An edit must not turn every finding into an error about vanished text.

    The excerpt below was verbatim when the reader wrote it and is gone now.
    Reporting it as fabricated would punish an honest edit, so the check
    reports the staleness once and leaves the quotes alone.
    """
    review = good_review()
    root = build(tmp_path, review, document="# Research tree\n\n- Q1: Rewritten entirely. [open]\n")
    findings = review_report(root)
    assert errors(findings) == []
    assert any("written about an earlier version" in f for f in findings)


def test_a_missing_document_is_an_error(tmp_path: Path) -> None:
    review = good_review()
    review["artifact"] = "GONE.md"
    root = build(tmp_path, review)
    hits = errors(review_report(root))
    assert len(hits) == 1
    assert "does not exist on disk" in hits[0]


def test_a_review_with_no_runs_warns(tmp_path: Path) -> None:
    review = good_review()
    review["runs"] = []
    root = build(tmp_path, review)
    assert any("review nobody ran is decoration" in f for f in review_report(root))


def test_an_unregistered_protocol_warns(tmp_path: Path) -> None:
    review = good_review()
    review["protocol"] = "read it"
    root = build(tmp_path, review)
    assert any("no protocol worth the name" in f for f in review_report(root))


def test_an_unrecognised_verdict_warns(tmp_path: Path) -> None:
    review = good_review()
    review["runs"][0]["verdict"] = "lgtm"
    root = build(tmp_path, review)
    assert any("unrecognised verdict" in f for f in review_report(root))


def test_a_quote_too_short_to_locate_warns(tmp_path: Path) -> None:
    review = good_review()
    review["runs"][0]["findings"][0]["excerpt"] = "Agents"
    root = build(tmp_path, review)
    assert any("too short to locate" in f for f in review_report(root))


def test_a_project_that_never_adopted_the_reader_channel_is_left_alone(tmp_path: Path) -> None:
    """Silence, not an invitation, for a project with no reviews at all.

    Telling every project on every run about a channel it has not adopted is
    the noise that teaches people to skim past the findings that matter.
    """
    root = build(tmp_path, None)
    assert review_report(root) == []


def test_a_document_left_unread_by_an_adopting_project_is_reported(tmp_path: Path) -> None:
    """Once a project reviews anything, a document nobody read is worth saying."""
    root = build(tmp_path, good_review())
    (root / "RESEARCH_LOG.md").write_text("# Log\n", encoding="utf-8")
    findings = review_report(root)
    assert errors(findings) == []
    assert any(
        "RESEARCH_LOG.md" in f and "never been read by an independent reader" in f for f in findings
    )


def test_reader_count_is_derived_from_the_runs_list(tmp_path: Path) -> None:
    """A stored count can contradict the list it summarises; a derived one cannot."""
    review = good_review()
    review["runs"].append(dict(review["runs"][0], reader="haiku"))
    review["readers"] = 99
    build(tmp_path, review)
    parsed = load_review(tmp_path / "reviews" / "tree-md.json")
    assert parsed is not None
    assert parsed.readers == 2


def test_an_unreadable_review_file_is_ignored_rather_than_crashing(tmp_path: Path) -> None:
    build(tmp_path, None)
    directory = tmp_path / "reviews"
    directory.mkdir(exist_ok=True)
    (directory / "broken.json").write_text("{not json", encoding="utf-8")
    findings = review_report(tmp_path)
    assert errors(findings) == []


@pytest.mark.parametrize(
    ("artifact", "expected"),
    [
        ("TREE.md", "tree-md"),
        ("RESEARCH_LOG.md", "research-log-md"),
        ("notes/q1-registration.md", "notes-q1-registration-md"),
    ],
)
def test_slugs_stay_unambiguous_across_directories(artifact: str, expected: str) -> None:
    assert slug_for(artifact) == expected


FINDING_EXCERPT = "Agents copy the style of whatever they are editing"


def test_waiving_a_real_finding_records_the_decision(tmp_path: Path) -> None:
    root = build(tmp_path, good_review())
    problem = record_waiver(
        root,
        "TREE.md",
        FINDING_EXCERPT,
        "The hypothesis line above names the mechanism.",
        "2026-08-24",
    )
    assert problem is None
    parsed = load_review(root / "reviews" / "tree-md.json")
    assert parsed is not None and len(parsed.waivers) == 1
    assert parsed.waiver_for({"excerpt": FINDING_EXCERPT}) is not None
    assert review_report(root) == []


def test_waiving_a_complaint_nobody_made_is_refused(tmp_path: Path) -> None:
    """A waiver is an answer to a specific complaint, not a blanket."""
    root = build(tmp_path, good_review())
    problem = record_waiver(
        root, "TREE.md", "an excerpt no reader quoted", "long enough grounds here", "2026-08-24"
    )
    assert problem is not None and "a reader actually made" in problem


def test_waiving_without_grounds_is_refused(tmp_path: Path) -> None:
    root = build(tmp_path, good_review())
    problem = record_waiver(root, "TREE.md", FINDING_EXCERPT, "fine", "2026-08-24")
    assert problem is not None and "too short" in problem


def test_a_waiver_left_dangling_by_hand_editing_warns(tmp_path: Path) -> None:
    """The CLI refuses dangling waivers, so one in the file means a hand edit."""
    review = good_review()
    review["waivers"] = [
        {
            "excerpt": "words no finding contains",
            "because": "long enough grounds here",
            "at": "2026-08-24",
        }
    ]
    root = build(tmp_path, review)
    assert any("waives a complaint no reader made" in f for f in review_report(root))


def test_a_rerun_of_the_reader_keeps_recorded_waivers(tmp_path: Path, monkeypatch) -> None:
    """A re-read replaces the runs, never the decisions someone recorded."""
    import review_clarity

    root = build(tmp_path, good_review())
    problem = record_waiver(
        root,
        "TREE.md",
        FINDING_EXCERPT,
        "The hypothesis line above names the mechanism.",
        "2026-08-24",
    )
    assert problem is None
    monkeypatch.setattr(
        review_clarity,
        "run_reader",
        lambda prompt, model, timeout: {"verdict": "clear", "findings": []},
    )
    config = review_clarity.ReaderConfig(readers=1)
    assert review_clarity.run_review(root, "TREE.md", config) == 0
    parsed = load_review(root / "reviews" / "tree-md.json")
    assert parsed is not None
    assert len(parsed.runs) == 1 and parsed.runs[0]["verdict"] == "clear"
    assert len(parsed.waivers) == 1, "the recorded waiver must survive the re-read"
