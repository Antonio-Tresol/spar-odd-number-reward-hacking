#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Layer 3 (operations): checks over clarity reviews written by a reader agent.

Whether a document reads clearly to someone outside the project is a
judgement, and no checker can make it. This project has direct evidence for
that: the phrase-level survey it ships flags "the same task" and "the first
sweep" as suspicious, because "is this word ordinary English" has no
mechanical answer. A checker that cries wolf gets bypassed and takes its true
positives with it, so the mechanical layer here judges nothing about writing.

What it does instead is the bargain the falsification scorecards already run.
The validator never rules on whether a falsification was any good; it rules
that a scorecard exists and that its verdict matches the claim. The same split
applies to prose. A reader agent stands in for the person the record is
actually for — a research partner with none of the writer's saved state: no
shared context window, no memory files, no scratch notes — and writes down
what they could not follow. This module checks that the reading happened,
that
it was of *this* text, and that every complaint points at words the file
actually contains.

A review lives in ``reviews/<slug>.json``:

    {
      "artifact": "TREE.md",
      "sha256": "<hash of the text that was read>",
      "protocol": "<what the reader was asked, written before it read>",
      "runs": [
        {"reader": "<model or person>", "at": "2026-08-24",
         "verdict": "needs-work",
         "findings": [{"excerpt": "<verbatim span from the file>",
                       "problem": "<what a reader cannot tell from it>"}]}
      ],
      "waivers": [
        {"excerpt": "<the finding's excerpt, verbatim>", "at": "2026-08-24",
         "because": "<why the text stays as it is>"}
      ]
    }

A finding is resolved one of two ways, both through the record command-line
tool. The primary way is to fix the text and run the reader again: the new
review either comes back clear or says what still does not communicate, and
nothing needs marking because resolution is re-derived from a fresh read. The
other way is to disagree: a waiver records, with a reason, the decision to
keep the text as it is. Waivers are dissent made visible, not deletion — the
finding stays in the review, the report shows it as waived with the reason,
and a waiver pointing at no finding is itself reported.

Three things make a review hard to fake, and each is a fact about text rather
than a matter of taste:

**Every finding quotes the file verbatim.** The excerpt must resolve against
the artifact, through the same resolver the claim-verification blocks use. A
reader cannot complain about a sentence that is not there, which is the
failure mode an agent asked to find problems will otherwise produce.

**Staleness is a hash, not a date.** A review stamped only with a date goes
stale silently the moment someone edits the file, and silent staleness is
indistinguishable from coverage. Recording the hash of the text that was read
makes "this review is of words that no longer exist" mechanically visible.

**Quotes are only checked against text they were written about.** When the
hash no longer matches, the review is reported as stale and its quotes are
left alone. Checking them anyway would turn one honest edit into a screenful
of errors about excerpts that were verbatim when the reader wrote them, which
is precisely how a checker teaches people to ignore it.

Everything here is advisory. A semantic verdict that can block a commit is a
semantic verdict that gets bypassed once and then forever; the review record
is the deliverable, and a missing or stale one is a reminder, never a gate.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Final, NamedTuple

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from research_graph_model import ERROR, INFO, WARNING  # noqa: E402
from research_graph_verification import MIN_ANCHOR_CHARS, quote_resolves  # noqa: E402

# One complaint: the words the reader quoted, and what it could not tell from
# them. One run: who read, when, the verdict, and that reader's complaints.
# One waiver: a recorded decision to keep the text a complaint points at.
Finding = dict[str, str]
ReaderRun = dict[str, Any]
Waiver = dict[str, str]

REVIEW_DIR: Final[str] = "reviews"

# The documents a research project shares with readers who were not present
# when they were written. Deliberately short: the reader channel is worth its
# cost where there is a measured baseline, and widening it to code comments is
# a separate question with a different noise profile.
REVIEWED: Final[tuple[str, ...]] = ("TREE.md", "RESEARCH_LOG.md")

VERDICTS: Final[frozenset[str]] = frozenset({"clear", "needs-work"})

# Short enough to be a placeholder rather than a registered instruction. A
# protocol written after reading can be shaped to the findings, so the point
# of recording one is that it was written before.
MIN_PROTOCOL_CHARS: Final[int] = 40

# A waiver is a decision against a reader's complaint, and a decision with no
# stated grounds cannot be revisited. Shorter than this is a brush-off.
MIN_WAIVER_CHARS: Final[int] = 20


class Review(NamedTuple):
    """One parsed review file: what was read, by whom, and what they found."""

    path: Path
    artifact: str
    sha256: str
    protocol: str
    runs: list[ReaderRun]
    waivers: list[Waiver]

    @property
    def readers(self) -> int:
        """How many readers reviewed this text.

        Derived from the runs list and never stored, for the same reason the
        claim-verification block derives its count: a stored number can
        contradict the list it summarises, a derived one cannot.
        """
        return len(self.runs)

    @property
    def findings(self) -> list[Finding]:
        """Every finding across every run, in the order they were recorded."""
        return [f for run in self.runs for f in (run.get("findings") or []) if isinstance(f, dict)]

    def waiver_for(self, finding: Finding) -> Waiver | None:
        """The waiver covering this finding, if one was recorded."""
        excerpt = _collapse(str(finding.get("excerpt", "")))
        for waiver in self.waivers:
            if _collapse(str(waiver.get("excerpt", ""))) == excerpt:
                return waiver
        return None


def _collapse(text: str) -> str:
    return " ".join(text.split())


def slug_for(artifact: str) -> str:
    """The review filename stem for an artifact path, unambiguous across directories."""
    return re.sub(r"[^a-z0-9]+", "-", artifact.lower()).strip("-")


def content_hash(path: Path) -> str | None:
    """The sha256 of a file's bytes, or None when it cannot be read."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def load_review(path: Path) -> Review | None:
    """One review file, or None when it is unreadable or not a review object."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not data.get("artifact"):
        return None
    runs = data.get("runs")
    waivers = data.get("waivers")
    return Review(
        path=path,
        artifact=str(data["artifact"]),
        sha256=str(data.get("sha256", "")),
        protocol=str(data.get("protocol", "")),
        runs=[run for run in runs if isinstance(run, dict)] if isinstance(runs, list) else [],
        waivers=[w for w in waivers if isinstance(w, dict)] if isinstance(waivers, list) else [],
    )


def load_reviews(root: Path) -> dict[str, Review]:
    """Every readable review under ``reviews/``, keyed by the artifact it reviewed."""
    directory = root / REVIEW_DIR
    if not directory.is_dir():
        return {}
    found: dict[str, Review] = {}
    for path in sorted(directory.glob("*.json")):
        review = load_review(path)
        if review is not None:
            found[review.artifact] = review
    return found


def is_current(root: Path, review: Review) -> bool:
    """Whether the review was written about the artifact's current content."""
    actual = content_hash(root / review.artifact)
    return actual is not None and actual == review.sha256


def _check_finding(root: Path, review: Review, finding: Finding) -> list[str]:
    """Findings for one recorded complaint: shape, anchor length, and resolution."""
    name = review.path.name
    excerpt = str(finding.get("excerpt", ""))
    if not excerpt or not str(finding.get("problem", "")):
        return [
            f'{WARNING}{name} has a review finding missing "excerpt" or "problem" — '
            "a complaint without the words it is about cannot be acted on."
        ]
    collapsed = " ".join(excerpt.split())
    if len(collapsed) < MIN_ANCHOR_CHARS:
        return [
            f"{WARNING}{name} quotes {collapsed!r}, too short to locate "
            f"(under {MIN_ANCHOR_CHARS} characters) — quote a longer verbatim span."
        ]
    resolved = quote_resolves(root, review.artifact, excerpt)
    if resolved is None:
        return [
            f"{ERROR}{name} reviews {review.artifact}, which cannot be read — "
            "restore the file or fix the artifact path."
        ]
    if not resolved:
        return [
            f"{ERROR}{name} quotes text that is not in {review.artifact}: "
            f"{collapsed[:80]!r} — a complaint that cannot be found in the file "
            "it cites is indistinguishable from an invented one; re-read the "
            "file and quote it verbatim."
        ]
    return []


def _check_runs(review: Review) -> list[str]:
    """Findings for the runs list itself: that it exists and speaks a known verdict."""
    name = review.path.name
    if not review.runs:
        return [
            f"{WARNING}{name} records no reader runs — a review nobody ran is "
            "decoration; record at least one run (reader, date, verdict, findings)."
        ]
    unknown = sorted(
        {
            str(run.get("verdict"))
            for run in review.runs
            if str(run.get("verdict", "")) not in VERDICTS
        }
    )
    if unknown:
        return [
            f"{WARNING}{name} has reader runs with an unrecognised verdict "
            f"({', '.join(unknown)}) — use one of: {', '.join(sorted(VERDICTS))}."
        ]
    return []


def _check_waivers(review: Review) -> list[str]:
    """Findings for the waivers: each must cover a real complaint, with real grounds."""
    name = review.path.name
    findings: list[str] = []
    recorded = {_collapse(str(f.get("excerpt", ""))) for f in review.findings}
    for waiver in review.waivers:
        excerpt = _collapse(str(waiver.get("excerpt", "")))
        if excerpt not in recorded:
            findings.append(
                f"{WARNING}{name} waives a complaint no reader made: "
                f"{excerpt[:60]!r} — a waiver must quote an existing finding's "
                "excerpt exactly; delete it or fix the quote."
            )
        if len(str(waiver.get("because", "")).strip()) < MIN_WAIVER_CHARS:
            findings.append(
                f"{WARNING}{name} has a waiver with no stated grounds — say why "
                "the text stays as it is, so the decision can be revisited."
            )
    return findings


def record_waiver(root: Path, artifact: str, excerpt: str, because: str, at: str) -> str | None:
    """Write one waiver into the artifact's review file, through the CLI only.

    Returns an explanation when the waiver cannot be recorded — no review,
    or no finding with that excerpt — and None on success. The excerpt must
    match a recorded finding exactly (whitespace aside): a waiver is an
    answer to a specific complaint, not a blanket.
    """
    review = load_reviews(root).get(artifact)
    if review is None:
        return f"no review of {artifact} exists yet; run the reader first."
    target = _collapse(excerpt)
    if all(_collapse(str(f.get("excerpt", ""))) != target for f in review.findings):
        return (
            f"no finding in {review.path.name} quotes {target[:60]!r}; "
            "a waiver must answer a complaint a reader actually made."
        )
    if review.waiver_for({"excerpt": excerpt}) is not None:
        return f"that finding is already waived in {review.path.name}."
    if len(because.strip()) < MIN_WAIVER_CHARS:
        return (
            f"the reason is too short (under {MIN_WAIVER_CHARS} characters) — "
            "say why the text stays as it is, so the decision can be revisited."
        )
    data = json.loads(review.path.read_text(encoding="utf-8"))
    data.setdefault("waivers", []).append({"excerpt": excerpt, "because": because, "at": at})
    review.path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return None


def _check_review(root: Path, review: Review) -> list[str]:
    """Every finding for one review file."""
    name = review.path.name
    findings: list[str] = []
    if not (root / review.artifact).exists():
        return [
            f"{ERROR}{name} reviews {review.artifact}, which does not exist on "
            "disk — fix the artifact path, or delete the review."
        ]
    if len(review.protocol.strip()) < MIN_PROTOCOL_CHARS:
        findings.append(
            f"{WARNING}{name} records no protocol worth the name — write down "
            "what the reader was asked, before it reads, so a later reader of "
            "the review can tell what question the verdict answers."
        )
    findings.extend(_check_runs(review))
    findings.extend(_check_waivers(review))
    if not is_current(root, review):
        findings.append(
            f"{INFO}{name} was written about an earlier version of "
            f"{review.artifact}, so its findings may already be fixed or stale — "
            "re-run the reader when the text settles."
        )
        return findings
    for finding in review.findings:
        findings.extend(_check_finding(root, review, finding))
    return findings


def _coverage(root: Path, reviews: dict[str, Review]) -> list[str]:
    """One line per shared document with no review, or a review of older text.

    Silent in a project that has never written a review. Adoption of the
    reader channel is a choice, and a report that tells every project on
    every run about a channel it has not adopted is noise that teaches
    people to skim the rest. Discovery belongs in the `review` command and
    in the skill, where someone is already asking.
    """
    if not reviews:
        return []
    findings: list[str] = []
    for artifact in REVIEWED:
        if not (root / artifact).exists():
            continue
        review = reviews.get(artifact)
        if review is None:
            findings.append(
                f"{INFO}{artifact} has never been read by an independent reader — "
                f"run 'review {artifact}' to learn what a research partner "
                "outside this session cannot follow."
            )
        elif not is_current(root, review):
            findings.append(
                f"{INFO}{artifact} has changed since it was last read — "
                f"run 'review {artifact}' again to cover the current text."
            )
    return findings


def review_report(root: Path) -> list[str]:
    """One finding per problem in the review records, plus what has never been read.

    Never returns a finding about the quality of any writing: that judgement
    belongs to the readers, and this report only says whether they made it,
    about which text, and whether their complaints point at real words.
    """
    reviews = load_reviews(root)
    findings: list[str] = []
    for artifact in sorted(reviews):
        findings.extend(_check_review(root, reviews[artifact]))
    findings.extend(_coverage(root, reviews))
    return findings
