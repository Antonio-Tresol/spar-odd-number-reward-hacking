#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Layer 3 (operations): the few names the record defines, and a rewrite prompt.

The plain-language contract has three failure modes. Two are mechanical:
abbreviations trip a pattern check, and an over-long node trips a length limit.
The third is a name invented in one session that every later reader has to
guess at, and it is not mechanical. Its fix is editorial: use the word the
field already uses, or describe the thing in ordinary words at each mention.
No checker can tell an invented name from ordinary English, so this module
does not pretend to. A survey of this project's own record found eighteen such
phrases in a record that passed every existing check.

What this module offers is therefore deliberately lopsided, and the asymmetry
is the whole design.

**Checked**, because it cannot produce a false alarm: a name the project chose
to declare must carry a definition, must actually appear somewhere in the
record, and must not be declared twice. Each is a fact about text the author
wrote, so a complaint is always about a real defect. Note what these checks do
*not* do: they never reward declaring a name, because declaring one was
already the wrong move in almost every case. A glossary is meant to stay
nearly empty, holding only names no description can replace, such as the
record's own file names and the values a field may take.

**Surveyed, never checked**: which phrases in the tree and log read like
invented names. A survey of this record flagged "the same task" and "the first
sweep", which are ordinary English, and this project has direct evidence that
a checker which cries wolf gets bypassed and takes its true positives with it.
So candidates are reported only by a command someone runs deliberately, ranked
so the likeliest read first, and the report asks for a rewrite rather than a
definition. Nothing here ever fails a build.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Final, NamedTuple

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from research_graph_model import ERROR, INFO, WARNING, Graph  # noqa: E402

GLOSSARY_HEADING: Final[re.Pattern[str]] = re.compile(r"^##\s+Glossary\s*$", re.MULTILINE)
NEXT_HEADING: Final[re.Pattern[str]] = re.compile(r"^(##\s+|---\s*$)", re.MULTILINE)
# "- **Term**: definition" — the shape the log template documents.
TERM_LINE: Final[re.Pattern[str]] = re.compile(
    r"^\s*[-*]\s+\*\*(?P<term>[^*]+)\*\*\s*:?\s*(?P<definition>.*)$"
)

# Nouns that a coined phrase in this kind of record tends to end with. Used
# only by the survey, never by a check.
SURVEY_NOUNS: Final[tuple[str, ...]] = (
    "task",
    "arm",
    "cell",
    "probe",
    "sweep",
    "gate",
    "path",
    "tripwire",
    "ladder",
    "lane",
    "harness",
    "runner",
    "pass",
)
SURVEY_PHRASE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:the|each|every|one|its)\s+([a-z][a-z-]{2,})\s+(" + "|".join(SURVEY_NOUNS) + r")\b"
)
# Ordinary English modifiers that make a phrase a description, not a coinage.
ORDINARY: Final[frozenset[str]] = frozenset(
    {
        "same",
        "first",
        "second",
        "third",
        "next",
        "last",
        "other",
        "whole",
        "single",
        "one",
        "each",
        "every",
        "final",
        "earlier",
        "later",
        "new",
        "old",
        "full",
        "real",
        "main",
        "own",
        "current",
        "original",
        "above",
        "following",
        "given",
        "identical",
        "opposite",
        "harder",
        "easier",
    }
)

MIN_DEFINITION_CHARS: Final[int] = 20


class Term(NamedTuple):
    """One glossary entry: the word being defined and what it is defined as."""

    term: str
    definition: str
    lineno: int


def parse_glossary(root: Path) -> list[Term]:
    """Every term defined under a '## Glossary' heading in the research log.

    An absent section is not an error — a small project may have no vocabulary
    worth defining — so it simply yields no terms.
    """
    log_path = root / "RESEARCH_LOG.md"
    try:
        text = log_path.read_text(encoding="utf-8")
    except OSError:
        return []
    heading = GLOSSARY_HEADING.search(text)
    if heading is None:
        return []
    body_start = heading.end()
    following = NEXT_HEADING.search(text, body_start)
    body = text[body_start : following.start() if following else len(text)]
    offset = text[:body_start].count("\n") + 1
    terms: list[Term] = []
    for index, line in enumerate(body.splitlines()):
        match = TERM_LINE.match(line)
        if match:
            term = match.group("term").strip()
            definition = match.group("definition").strip()
            # "**Research tree** (`TREE.md`): the ..." puts the file name
            # between the term and its colon; keep it with the term so the
            # printed line reads as one name and one sentence.
            aside = re.match(r"^\((?P<aside>[^)]*)\)\s*:?\s*(?P<rest>.*)$", definition)
            if aside:
                term = f"{term} ({aside.group('aside')})"
                definition = aside.group("rest").strip()
            terms.append(Term(term, definition, offset + index))
    return terms


def _record_text(root: Path, graph: Graph, skip_glossary: bool = False) -> str:
    """All prose a reader meets: node text plus the log, lowercased.

    With `skip_glossary`, the glossary section itself is cut out first. The
    usage check needs that: a term's own definition line mentions the term, so
    including it would make every entry look used and the check inert — which
    is exactly what its test caught.
    """
    parts = [node.text for node in graph.nodes.values()]
    try:
        log = (root / "RESEARCH_LOG.md").read_text(encoding="utf-8")
    except OSError:
        log = ""
    if skip_glossary and log:
        heading = GLOSSARY_HEADING.search(log)
        if heading:
            following = NEXT_HEADING.search(log, heading.end())
            end = following.start() if following else len(log)
            log = log[: heading.start()] + log[end:]
    parts.append(log)
    return " ".join(parts).lower()


def glossary_report(root: Path, graph: Graph) -> list[str]:
    """Findings about declared terms only — never about undeclared ones.

    Three checks, each a fact about text the author wrote: a declared term
    carries a real definition, is not declared twice, and is actually used
    somewhere in the record. A glossary entry nobody uses is not a harmless
    extra; it is a term the reader will hunt for and never meet, which is the
    same confusion in the opposite direction.
    """
    terms = parse_glossary(root)
    if not terms:
        return []
    findings: list[str] = []
    haystack = _record_text(root, graph, skip_glossary=True)
    seen: dict[str, int] = {}
    for entry in terms:
        key = entry.term.lower()
        if key in seen:
            findings.append(
                f"{ERROR}the glossary defines {entry.term!r} twice (lines "
                f"{seen[key]} and {entry.lineno}) — keep one definition so the "
                "record has one meaning for the word."
            )
            continue
        seen[key] = entry.lineno
        if len(entry.definition) < MIN_DEFINITION_CHARS:
            findings.append(
                f"{ERROR}the glossary entry for {entry.term!r} has no real definition "
                f"(RESEARCH_LOG.md:{entry.lineno}) — say what the term means in a "
                "sentence a reader outside this project would understand."
            )
            continue
        bare = key.split("(")[0].strip().strip("`")
        if bare and bare not in haystack:
            findings.append(
                f"{WARNING}the glossary defines {entry.term!r} but nothing in the tree "
                "or the log uses it — delete the entry, or use the term where the "
                "record currently says something else."
            )
    findings.append(f"{INFO}the glossary defines {len(seen)} term(s).")
    return findings


def survey_candidates(root: Path, graph: Graph) -> list[tuple[str, int, bool]]:
    """Phrases that may be undeclared coinages, most frequent first.

    Advisory only. The filter drops phrases whose modifier is ordinary English
    ("the same task"), which removes the obvious false alarms, but nothing here
    is reliable enough to fail a build on — which is exactly why no check calls
    this function.
    """
    defined = {term.term.lower().split("(")[0].strip().strip("`") for term in parse_glossary(root)}
    counts: dict[str, int] = {}
    for modifier, noun in SURVEY_PHRASE.findall(_record_text(root, graph)):
        if modifier in ORDINARY:
            continue
        counts[f"{modifier} {noun}"] = counts.get(f"{modifier} {noun}", 0) + 1
    rows = [
        (phrase, count, any(phrase.split()[0] in term or term in phrase for term in defined))
        for phrase, count in counts.items()
    ]
    rows.sort(key=lambda row: (row[2], -row[1], row[0]))
    return rows
