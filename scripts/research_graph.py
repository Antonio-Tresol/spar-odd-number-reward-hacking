#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Interfaces layer: the command-line entry point agents and humans use to
navigate, verify, and extend the research record as a typed graph.

Presentation only: every handler calls research_graph_model (domain model and
loader), research_graph_checks (read-only checks), or research_graph_write
(validated writes), then formats the result. Every command is declared once
in COMMAND_REGISTRY — name, one-sentence help, arguments, handler — and both
argparse's subparsers and the agent-facing `help` command are generated from
it, so the documented commands and the runnable commands can never drift
apart.

Run: uv run scripts/research_graph.py <command>. For an agent-oriented guide
assuming no prior context, run: uv run scripts/research_graph.py help"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Final

import research_graph_checks as checks
import research_graph_glossary as glossary
import research_graph_model as model
import research_graph_review as review
import research_graph_views as views
import research_graph_write as write
import review_clarity
from research_graph_model import OK as EXIT_OK
from research_graph_model import USAGE as EXIT_USAGE

NODE_TYPES: Final[tuple[str, ...]] = ("question", "hypothesis", "experiment", "claim")

# The read-only commands are rendered in research_graph_views; the registry below
# points straight at them, so a navigation command is declared here and drawn there.
cmd_tree = views.cmd_tree
cmd_show = views.cmd_show
cmd_path = views.cmd_path
cmd_search = views.cmd_search
cmd_evidence = views.cmd_evidence
cmd_orphans = views.cmd_orphans
cmd_json = views.cmd_json
cmd_mermaid = views.cmd_mermaid

# Curated recipes for the `help` command: exact command lines under task
# headings, kept separate from COMMAND_REGISTRY since a recipe is a workflow.
RECIPES: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    (
        "Start of session",
        (
            "uv run scripts/research_graph.py verify",
            "uv run scripts/research_graph.py tree",
            "uv run scripts/research_graph.py show Q1",
        ),
    ),
    (
        "Record an experiment result (write the log entry first: a node may only "
        "cite a log date that already exists)",
        (
            'uv run scripts/research_graph.py log --did "<did>" --expected "<expected>" '
            '--changes "<changes>" --next "<next>"',
            "uv run scripts/research_graph.py set-status Q1.H1.E1 done "
            "--evidence results/run1.jsonl results/run2.jsonl --log-date <today>",
            'uv run scripts/research_graph.py add claim "<one falsifiable sentence>" '
            "--parent Q1.H1.E1 --evidence results/run1.jsonl",
        ),
    ),
    (
        "Move an over-long node's detail into a document (nodes stay short)",
        (
            'uv run scripts/research_graph.py add-note <slug> "<title>" "<the protocol '
            'text that was inlined>" --link Q1.H1.E1',
            'uv run scripts/research_graph.py set-text Q1.H1.E1 "<one or two plain '
            'sentences, pointing at the document>"',
        ),
    ),
    (
        "Decide a claim's status after the falsification pass",
        (
            "uv run scripts/research_graph.py pin Q1.H1.E1.C1",
            "uv run scripts/research_graph.py set-status Q1.H1.E1.C1 survived "
            "--evidence results/falsify_scorecard.json",
        ),
    ),
    (
        "Ask an outside reader what the record fails to communicate, then resolve "
        "each finding: fix the text and read again, or keep it and say why",
        (
            "uv run scripts/research_graph.py review --run TREE.md",
            "uv run scripts/research_graph.py review",
            'uv run scripts/research_graph.py set-text Q1.H1.E1 "<the plain rewrite>"',
            "uv run scripts/research_graph.py review --waive TREE.md "
            '--quote "<the finding\'s excerpt>" --because "<why the text stays>"',
        ),
    ),
    (
        "After a compaction or with no context, run",
        (
            "uv run scripts/research_graph.py tree",
            "uv run scripts/research_graph.py verify",
        ),
    ),
)

Arg = tuple[tuple[str, ...], dict[str, object]]


def arg(*flags: str, **kwargs: object) -> Arg:
    """Build one argparse argument declaration for a COMMAND_REGISTRY entry."""
    return flags, kwargs


@dataclass(frozen=True)
class CommandSpec:
    """One CLI command: its name, one-sentence help, arguments, and handler."""

    name: str
    help: str
    args: tuple[Arg, ...]
    handler: Callable[[argparse.Namespace], int]


def _default_root() -> Path:
    """The repository root two levels above this script, matching validate_research.py."""
    return Path(__file__).resolve().parent.parent


# Checks dispatch: thin wrappers over research_graph_checks.


def cmd_verify(args: argparse.Namespace) -> int:
    return checks.verify(args.root)


def _print_review(root: Path, artifact: str, record: "review.Review") -> None:
    """One artifact's review: reader runs, then each finding as open or waived."""
    state = "current" if review.is_current(root, record) else "STALE (the text has changed)"
    latest = max((str(run.get("at", "")) for run in record.runs), default="unknown")
    print(f"{artifact} — {record.readers} reader(s), last read {latest}, {state}")
    if not record.findings:
        print("  no findings: every reader followed the whole document")
    for finding in record.findings:
        excerpt = " ".join(str(finding.get("excerpt", "")).split())
        waiver = record.waiver_for(finding)
        mark = "waived" if waiver else "open"
        print(f"  [{mark}] {excerpt[:70]!r}")
        print(f"      {finding.get('problem', '')}")
        if waiver:
            print(f"      kept as written because: {waiver.get('because', '')}")


def cmd_review(args: argparse.Namespace) -> int:
    """Run, report, or resolve independent-reader reviews of the shared documents."""
    if args.run:
        config = review_clarity.ReaderConfig(model=args.model, readers=args.readers)
        return review_clarity.run_review(args.root, args.run, config)
    if args.waive:
        problem = review.record_waiver(
            args.root,
            args.waive,
            args.quote or "",
            args.because or "",
            datetime.date.today().isoformat(),
        )
        if problem:
            print(f"cannot waive: {problem}", file=sys.stderr)
            return EXIT_USAGE
        print(f"waived, with the reason on record; 'review' shows it under {args.waive}.")
        return EXIT_OK
    reviews = review.load_reviews(args.root)
    if not reviews:
        print(
            "No document has been read by an independent reader yet. Whether "
            "prose communicates is a judgement no checker here can make, so a "
            "reader agent makes it: run\n"
            "  uv run scripts/research_graph.py review --run TREE.md\n"
            "It reads the document with no access to this repository or this "
            "conversation, and writes what a research partner outside this "
            "session could not follow to "
            f"{review.REVIEW_DIR}/. Fix what it finds and run the reader again, "
            "or keep the text and record why with --waive. Findings are "
            "advisory and never fail a build."
        )
        return EXIT_OK
    for artifact in sorted(reviews):
        _print_review(args.root, artifact, reviews[artifact])
    return EXIT_OK


def cmd_glossary(args: argparse.Namespace) -> int:
    """Print the record's defined names, or survey it for phrases worth rewriting."""
    graph = model.load(args.root)
    if args.survey:
        rows = glossary.survey_candidates(args.root, graph)
        if not rows:
            print("No candidate project terms found in the tree or the log.")
            return EXIT_OK
        print(
            "Phrases that read like invented names a reader would have to guess "
            "at, most used first. Rewrite each real one in standard words or a "
            "plain description; define a name only when no description can "
            "replace it. This is a survey, not a check: nothing here fails a "
            "build, and ordinary English can still appear."
        )
        for phrase, count, covered in rows:
            mark = "defined" if covered else "rewrite or define"
            print(f"  {phrase:34} used {count:3}x   {mark}")
        return EXIT_OK
    terms = glossary.parse_glossary(args.root)
    if not terms:
        print(
            "This record defines no terms, which is the healthy default: the "
            "tree and the log are meant to read in ordinary English and "
            "standard field vocabulary. Add a '## Glossary' section to "
            "RESEARCH_LOG.md only for a name no description can replace, such "
            "as a file name or the values a field is allowed to take. Run "
            "'glossary --survey' to find phrases worth rewriting."
        )
        return EXIT_OK
    for term in terms:
        print(f"{term.term}: {term.definition}")
    return EXIT_OK


def cmd_pin(args: argparse.Namespace) -> int:
    result = checks.compute_pin(args.root, args.ids)
    print(json.dumps(result, indent=2))
    print(
        'Embed this dict under the "provenance" key of the scorecard evidence file '
        "you are about to write for these claims. If agents verified the claim by "
        'reading traces, literature, or code, also record a "verification" block '
        "there (the validate-claims skill has the schema); verify re-checks its "
        "quote anchors against the pinned files."
    )
    return EXIT_OK


# Write dispatch: thin wrappers over research_graph_write. Every write command
# follows the same transaction contract inside that module, so these handlers
# only translate parsed arguments into one call and return its exit code — no
# formatting or validation logic belongs here.


def cmd_add(args: argparse.Namespace) -> int:
    return write.add_node(
        args.root,
        args.parent,
        args.type,
        args.text,
        args.status,
        args.evidence or [],
        dry_run=args.dry_run,
    )


def cmd_add_evidence(args: argparse.Namespace) -> int:
    return write.add_evidence(args.root, args.id, args.paths, dry_run=args.dry_run)


def cmd_set_status(args: argparse.Namespace) -> int:
    return write.set_status(
        args.root, args.id, args.status, args.evidence or [], args.log_date, dry_run=args.dry_run
    )


def cmd_set_text(args: argparse.Namespace) -> int:
    return write.set_text(args.root, args.id, args.text, dry_run=args.dry_run)


def cmd_log(args: argparse.Namespace) -> int:
    return write.append_log_entry(
        args.root,
        args.date,
        args.did,
        args.expected,
        args.changes,
        args.next,
        dry_run=args.dry_run,
    )


def cmd_add_note(args: argparse.Namespace) -> int:
    return write.add_note(
        args.root, args.slug, args.title, args.body, args.link, dry_run=args.dry_run
    )


def cmd_help(args: argparse.Namespace) -> int:
    print("Commands:")
    for spec in COMMAND_REGISTRY:
        print(f"  {spec.name:<14} {spec.help}")
    print()
    print("Add --dry-run to any write command to preview its exact output before committing.")
    print()
    print("Recipes for common agent workflows, as exact command lines:")
    for heading, lines in RECIPES:
        print(f"\n{heading}:")
        for line in lines:
            print(f"  {line}")
    return EXIT_OK


# The command registry: the single source every subparser and the help text
# below are generated from. DRY_RUN is shared by every write command so the
# flag's wording never drifts between them.
DRY_RUN: Final[Arg] = arg(
    "--dry-run",
    action="store_true",
    help="Rehearse the write, report the validator's verdict, and leave the files untouched.",
)

COMMAND_REGISTRY: Final[tuple[CommandSpec, ...]] = (
    CommandSpec(
        "tree",
        "Print the tree as an indented outline: id, status, and text truncated to 80 characters.",
        (
            arg("--type", choices=NODE_TYPES, help="Only show nodes of this type."),
            arg("--status", help="Only show nodes with exactly this status."),
            arg("--under", help="Only show this node id and its descendants."),
        ),
        cmd_tree,
    ),
    CommandSpec(
        "show",
        "Print every field for one node, its evidence, and what mentions it in the log and notes.",
        (arg("id", help="The node id to show, for example Q1.H1.E2."),),
        cmd_show,
    ),
    CommandSpec(
        "path",
        "Print the chain from the root question down to one node, one line each.",
        (arg("id", help="The node id whose ancestor chain to print."),),
        cmd_path,
    ),
    CommandSpec(
        "search",
        "Search node text, log entries, and document titles and paths for a term, and show "
        "each hit.",
        (arg("term", help="The text to search for, case-insensitively."),),
        cmd_search,
    ),
    CommandSpec(
        "evidence",
        "Print an evidence table: path, kind, whether it exists, and whether it is pinned "
        "and drifted.",
        (
            arg("id", nargs="?", help="Only this node's evidence. Omit for every node's."),
            arg(
                "--graduated",
                action="store_true",
                help="Limit to claims whose status has been decided: survived, weakened, or failed.",
            ),
        ),
        cmd_evidence,
    ),
    CommandSpec(
        "orphans",
        "Print notes files that no node evidence links and no tree or log text mentions.",
        (),
        cmd_orphans,
    ),
    CommandSpec(
        "json",
        "Print the record as the versioned JSON graph, or write it to a file.",
        (arg("--out", type=Path, help="Write to this file instead of standard output."),),
        cmd_json,
    ),
    CommandSpec(
        "mermaid",
        "Print the record as a Mermaid flowchart, or write it to a file.",
        (
            arg("--evidence", action="store_true", help="Add edges to each node's evidence."),
            arg("--out", type=Path, help="Write to this file instead of standard output."),
        ),
        cmd_mermaid,
    ),
    CommandSpec(
        "verify",
        "Run every integrity check and report pass or fail: grammar, evidence, drift, orphans.",
        (),
        cmd_verify,
    ),
    CommandSpec(
        "review",
        "Run an independent reader over a shared document, report what readers "
        "found, or record why a finding's text stays as written.",
        (
            arg(
                "--run",
                metavar="ARTIFACT",
                help="Read this document with fresh reader agents and record what "
                "they could not follow.",
            ),
            arg("--readers", type=int, default=1, help="Readers to run (default: 1)."),
            arg("--model", default="sonnet", help="Reader model (default: sonnet)."),
            arg(
                "--waive",
                metavar="ARTIFACT",
                help="Keep the text a finding points at, recording the decision.",
            ),
            arg("--quote", help="The finding's excerpt, verbatim (with --waive)."),
            arg("--because", help="Why the text stays as it is (with --waive)."),
        ),
        cmd_review,
    ),
    CommandSpec(
        "glossary",
        "Print the terms this record defines, or survey the text for terms it does not.",
        (
            arg(
                "--survey",
                action="store_true",
                help="List phrases that may be undefined project terms (advisory, never fails).",
            ),
        ),
        cmd_glossary,
    ),
    CommandSpec(
        "pin",
        "Record what a claim rests on — the commit, the date, and a hash of every "
        "evidence file — to embed in its falsification report.",
        (arg("ids", nargs="+", help="One or more claim ids, for example Q1.H1.E1.C1."),),
        cmd_pin,
    ),
    CommandSpec(
        "add",
        "Add a question, hypothesis, experiment, or claim node under a parent, with the "
        "next free id.",
        (
            arg("type", choices=NODE_TYPES, help="The kind of node to add."),
            arg("text", help="The node's headline text, under 1,200 characters."),
            arg("--parent", help="The parent node's id. Required unless type is question."),
            arg("--status", help="Initial status. Omit to take the type's default."),
            arg(
                "--evidence",
                nargs="+",
                action="extend",
                help="Evidence paths to attach immediately, space-separated "
                "(repeating the flag adds to the list rather than replacing it).",
            ),
            DRY_RUN,
        ),
        cmd_add,
    ),
    CommandSpec(
        "add-evidence",
        "Attach one or more evidence paths to an existing node.",
        (
            arg("id", help="The node id to attach evidence to."),
            arg("paths", nargs="+", help="One or more repo-relative evidence paths."),
            DRY_RUN,
        ),
        cmd_add_evidence,
    ),
    CommandSpec(
        "set-status",
        "Change a node's status, optionally attaching evidence and a log date in the same edit.",
        (
            arg("id", help="The node id to change."),
            arg("status", help="The new status, from the vocabulary for that node's type."),
            arg(
                "--evidence",
                nargs="+",
                action="extend",
                help="Evidence paths to attach with the status change, space-separated "
                "(repeating the flag adds to the list rather than replacing it).",
            ),
            arg("--log-date", help="A RESEARCH_LOG.md date (YYYY-MM-DD) explaining this change."),
            DRY_RUN,
        ),
        cmd_set_status,
    ),
    CommandSpec(
        "set-text",
        "Rewrite a node's headline text, keeping its status, evidence, and log date.",
        (
            arg("id", help="The node id whose text to rewrite."),
            arg("text", help="The new text: one or two plain sentences."),
            DRY_RUN,
        ),
        cmd_set_text,
    ),
    CommandSpec(
        "log",
        "Append today's (or a given date's) log entry, merging into an existing entry for "
        "that date.",
        (
            arg("--date", help="YYYY-MM-DD. Defaults to today; must not predate the newest entry."),
            arg("--did", required=True, help="What I did."),
            arg("--expected", required=True, help="What I expected versus what happened."),
            arg("--changes", required=True, help="What this changes about my thinking."),
            arg("--next", required=True, help="What I will do next."),
            DRY_RUN,
        ),
        cmd_log,
    ),
    CommandSpec(
        "add-note",
        "Create a dated document under notes/, optionally linking it as evidence on a node.",
        (
            arg("slug", help="Filename stem: creates notes/<slug>.md."),
            arg("title", help="The document's title heading."),
            arg("body", help="The document's body text."),
            arg("--link", help="A node id to attach this note's path to as evidence."),
            DRY_RUN,
        ),
        cmd_add_note,
    ),
    CommandSpec(
        "help",
        "Print every command's one-line help plus curated recipes for common agent workflows.",
        (),
        cmd_help,
    ),
)


def build_parser() -> argparse.ArgumentParser:
    """Build the full CLI from COMMAND_REGISTRY, so every command is documented once."""
    parser = argparse.ArgumentParser(
        prog="research_graph.py",
        description="Navigate, verify, and extend the research record as a typed graph. "
        "Run 'research_graph.py help' for an agent-oriented guide with recipes.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=_default_root(),
        help="Path to the project root containing TREE.md and RESEARCH_LOG.md. Defaults to "
        "the repository root two levels above this script, the same convention "
        "validate_research.py uses.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="command")
    for spec in COMMAND_REGISTRY:
        sub = subparsers.add_parser(spec.name, help=spec.help, description=spec.help)
        for flags, kwargs in spec.args:
            sub.add_argument(*flags, **kwargs)
        sub.set_defaults(handler=spec.handler)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch to the matched command's handler.

    A bad --root surfaces as FileNotFoundError from research_graph_model.load
    with an already-plain-language message; that is a usage mistake, not a
    record-validity failure, so it is caught once here at exit code 2."""
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except FileNotFoundError as error:
        print(f"Error: {error}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
