"""Tests for the CLI front door.

These exist because of a specific failure. A rename left `cli.py` importing a
name that no longer existed and using another it never imported, and the full
156-test suite passed — because nothing imported `cli.py`. The front door was
the only unreachable module in the package, so the one file every user touches
first was the one file no test loaded.

So the point here is coverage, not cleverness: importing the module and building
the parser is enough to turn a broken import into a failing test instead of a
traceback in someone's terminal.

Run:  uv run pytest tests/test_cli.py
"""

from __future__ import annotations

import pytest

from odd_number import cli


def test_the_module_imports() -> None:
    """A broken import in the front door must fail here, not in a user's shell."""
    assert cli.main is not None


def test_every_subcommand_is_reachable() -> None:
    parser = cli.build_parser()
    actions = [a for a in parser._subparsers._actions if hasattr(a, "choices") and a.choices]
    names = set(actions[0].choices)
    assert names == {
        "prompts",
        "models",
        "endpoints",
        "collect",
        "audit",
        "grade",
        "validate-judge",
        "branch",
        "branch-figure",
        "gaming-figure",
        "export-traces",
        "build-explainer",
        "interview",
    }


def test_every_subcommand_binds_a_handler() -> None:
    """`main` calls `args.func`, so a subcommand without one crashes at runtime."""
    parser = cli.build_parser()
    choices = next(a.choices for a in parser._subparsers._actions if getattr(a, "choices", None))
    for name, sub in choices.items():
        assert callable(sub.get_default("func")), f"{name} has no handler"


def test_collect_defaults_to_a_pinned_model() -> None:
    args = cli.build_parser().parse_args(["collect", "--mock", "--n", "1"])
    assert args.mock is True
    assert args.n == 1
    assert cli.build_sampling(args).temperature == 1.0


def test_sampling_flags_reach_the_config() -> None:
    args = cli.build_parser().parse_args(
        ["collect", "--temperature", "0.5", "--top-p", "0.8", "--max-tokens", "99"]
    )
    sampling = cli.build_sampling(args)
    assert (sampling.temperature, sampling.top_p, sampling.max_tokens) == (0.5, 0.8, 99)


def test_a_command_is_required() -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args([])
