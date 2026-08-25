#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pytest>=8.0", "lanorme"]
# ///
"""Tests for the harness's checks.

Two things are tested, and the second matters more:

  * that each rule FIRES on the thing it is meant to catch, and
  * that it STAYS QUIET on realistic input it should not touch.

The false-positive tests exist because every false positive found so far was
found by accident, in the middle of doing something else. A checker that cries
wolf gets bypassed, and then the true positives go unread too. Each `quiet_*`
test below encodes a specific false positive that was actually shipped.

Run:  uv run tests/test_checks.py        (or: uv run --with pytest pytest tests/)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lanorme_plugins._common import is_glob_match  # noqa: E402
from lanorme_plugins.provenance import ProvenanceCheck  # noqa: E402
from lanorme_plugins.skill_portability import SkillPortabilityCheck  # noqa: E402
from lanorme_plugins.tensors import TensorsCheck  # noqa: E402

SKILL_BODY = "\n".join(f"Body line {i} with real content." for i in range(8))


def write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def make_skill(root: Path, name: str, frontmatter: str, body: str = SKILL_BODY) -> None:
    write(root, f".claude/skills/{name}/SKILL.md", f"---\n{frontmatter}\n---\n\n{body}\n")


def codes(result: object) -> list[str]:
    """Rule codes reported, violations and warnings together."""
    return [v.code for v in [*result.violations, *result.warnings]]  # type: ignore[attr-defined]


# --------------------------------------------------------------------------
# Glob matching. The shipped default `reports/**/*.md` silently matched nothing
# for files directly inside reports/, because fnmatch requires a separator.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "pattern", "expected"),
    [
        ("reports/findings.md", "reports/**/*.md", True),  # regression: was False
        ("reports/a/b/deep.md", "reports/**/*.md", True),
        ("README.md", "**/*.md", True),  # regression: was False
        ("notes/a/b.md", "**/*.md", True),
        ("src/main.py", "**/*.md", False),
        ("otherdir/findings.md", "reports/**/*.md", False),
        ("reports/findings.txt", "reports/**/*.md", False),
    ],
)
def test_glob_semantics(path: str, pattern: str, expected: bool) -> None:
    assert is_glob_match(path, [pattern]) is expected


# --------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------


def test_provenance_fires_on_wrong_value(tmp_path: Path) -> None:
    write(tmp_path, "results/r.json", json.dumps({"rate": 0.43}))
    write(tmp_path, "doc.md", "Rate was 50%.\n<!-- claim: 0.50 from results/r.json#rate -->\n")
    assert "PROV-002" in codes(ProvenanceCheck().run(src_root=str(tmp_path)))


def test_provenance_fires_on_missing_file_and_key(tmp_path: Path) -> None:
    write(tmp_path, "results/r.json", json.dumps({"rate": 0.43}))
    write(tmp_path, "a.md", "x\n<!-- claim: 0.1 from results/gone.json#rate -->\n")
    write(tmp_path, "b.md", "x\n<!-- claim: 0.1 from results/r.json#nope -->\n")
    assert codes(ProvenanceCheck().run(src_root=str(tmp_path))).count("PROV-001") == 2


def test_provenance_quiet_on_rounded_value(tmp_path: Path) -> None:
    """0.37 in prose against 0.3712 on disk agrees to the precision written."""
    write(tmp_path, "results/r.json", json.dumps({"rate": 0.3712}))
    write(tmp_path, "doc.md", "37%.\n<!-- claim: 0.37 from results/r.json#rate -->\n")
    assert codes(ProvenanceCheck().run(src_root=str(tmp_path))) == []


def test_provenance_quiet_on_explicit_tolerance(tmp_path: Path) -> None:
    write(tmp_path, "results/r.json", json.dumps({"rate": 0.44}))
    write(tmp_path, "doc.md", "44%.\n<!-- claim: 0.43 from results/r.json#rate tol=0.02 -->\n")
    assert codes(ProvenanceCheck().run(src_root=str(tmp_path))) == []


def test_provenance_quiet_inside_code_fence(tmp_path: Path) -> None:
    """Documentation showing the syntax is not a claim about this project."""
    write(
        tmp_path,
        "doc.md",
        "Example:\n\n```markdown\n<!-- claim: 0.9 from results/x.json#k -->\n```\n",
    )
    assert codes(ProvenanceCheck().run(src_root=str(tmp_path))) == []


def test_provenance_resolves_list_indices(tmp_path: Path) -> None:
    write(tmp_path, "results/r.json", json.dumps({"runs": [{"acc": 0.8}, {"acc": 0.9}]}))
    write(
        tmp_path, "doc.md", "Second run 0.90.\n<!-- claim: 0.9 from results/r.json#runs.1.acc -->\n"
    )
    assert codes(ProvenanceCheck().run(src_root=str(tmp_path))) == []


def test_prov003_quiet_once_the_file_has_any_marker(tmp_path: Path) -> None:
    """One marker adopts the convention for the whole file. Distinguishing a
    result from a hyperparameter per line is judgement a regex cannot make."""
    write(tmp_path, "results/r.json", json.dumps({"rate": 0.43}))
    write(
        tmp_path,
        "reports/f.md",
        "We set the learning rate to 0.001.\n\n"
        "Rate was 43%.\n<!-- claim: 0.43 from results/r.json#rate -->\n\n"
        "The threshold p < 0.05 is conventional.\n",
    )
    check = ProvenanceCheck()
    check.configure(settings={"claim_bearing": ["reports/**/*.md"]})
    assert codes(check.run(src_root=str(tmp_path))) == []


def test_prov003_caps_at_one_warning_per_file(tmp_path: Path) -> None:
    """The per-file cap is the design: a regex cannot tell a result from a
    hyperparameter, so a markerless file gets one nudge, never a wall. An
    earlier per-line version produced five warnings on this exact file."""
    write(
        tmp_path,
        "reports/methods.md",
        "We use the conventional threshold of p < 0.05 throughout.\n"
        "We set the learning rate to 0.001 and dropout to 0.15.\n\n"
        "> The largest model agrees on 78% of items.\n\n"
        "See https://example.org/page?v=0.99 and `alpha = 0.05`.\n"
        "The detector fired on 41% of prompts overall.\n",
    )
    check = ProvenanceCheck()
    check.configure(settings={"claim_bearing": ["reports/**/*.md"]})
    assert codes(check.run(src_root=str(tmp_path))).count("PROV-003") <= 1


def test_provenance_parses_scientific_notation(tmp_path: Path) -> None:
    """3e-05 was unparseable: reported unmarked AND never validated."""
    write(tmp_path, "results/r.json", json.dumps({"pval": 3e-05}))
    write(tmp_path, "doc.md", "p was tiny.\n<!-- claim: 3e-05 from results/r.json#pval -->\n")
    assert codes(ProvenanceCheck().run(src_root=str(tmp_path))) == []


def test_prov003_fires_on_a_report_with_no_markers_at_all(tmp_path: Path) -> None:
    write(tmp_path, "reports/f.md", "The detector fired on 41% of prompts overall.\n")
    check = ProvenanceCheck()
    check.configure(settings={"claim_bearing": ["reports/**/*.md"]})
    found = codes(check.run(src_root=str(tmp_path)))
    assert found.count("PROV-003") == 1


def test_prov003_off_by_default(tmp_path: Path) -> None:
    """Opt-in: no claim_bearing configured means no PROV-003 anywhere."""
    write(tmp_path, "reports/f.md", "An unmarked rate of 22.5% appears here.\n")
    assert codes(ProvenanceCheck().run(src_root=str(tmp_path))) == []


def test_provenance_quiet_on_prose_without_numbers(tmp_path: Path) -> None:
    write(tmp_path, "reports/f.md", "This document discusses methodology and cites no figures.\n")
    check = ProvenanceCheck()
    check.configure(settings={"claim_bearing": ["reports/**/*.md"]})
    assert codes(check.run(src_root=str(tmp_path))) == []


# --------------------------------------------------------------------------
# Tensors
# --------------------------------------------------------------------------


def test_tensors_fires_on_bare_annotations_including_vectors(tmp_path: Path) -> None:
    write(
        tmp_path,
        "m.py",
        "from torch import Tensor\n\ndef f(x: Tensor, v: Tensor) -> Tensor:\n    return x\n",
    )
    found = codes(TensorsCheck().run(src_root=str(tmp_path)))
    assert found.count("TENSOR-001") == 3  # two parameters and the return


def test_tensors_fires_on_raw_shape_ops(tmp_path: Path) -> None:
    write(tmp_path, "m.py", "import torch\n\ndef f(x):\n    return x.view(1, -1).permute(1, 0)\n")
    assert codes(TensorsCheck().run(src_root=str(tmp_path))).count("TENSOR-002") == 2


# --- Regression tests from adversarial review ---------------------------
# Each pins a false positive an adversarial pass actually produced.


def test_tensors_quiet_on_pandas(tmp_path: Path) -> None:
    """DataFrame.transpose and .squeeze are not tensor reshapes."""
    write(
        tmp_path,
        "m.py",
        "import pandas as pd\n\n"
        "def summarise(frame: pd.DataFrame) -> pd.DataFrame:\n"
        "    return frame.transpose().squeeze()\n",
    )
    assert codes(TensorsCheck().run(src_root=str(tmp_path))) == []


def test_tensors_quiet_on_unrelated_class_named_tensor(tmp_path: Path) -> None:
    """A symbolic `Tensor` with no shape cannot satisfy a jaxtyping annotation."""
    write(
        tmp_path,
        "m.py",
        "from dataclasses import dataclass\n\n@dataclass\nclass Tensor:\n"
        "    symbol: str\n\ndef negate(t: Tensor) -> Tensor:\n    return t\n",
    )
    assert codes(TensorsCheck().run(src_root=str(tmp_path))) == []


def test_tensors_quiet_on_orm_and_list_helpers(tmp_path: Path) -> None:
    write(
        tmp_path,
        "m.py",
        "import sqlalchemy\n\ndef go(table, rows):\n"
        "    table.view('active')\n    return rows.flatten()\n",
    )
    assert codes(TensorsCheck().run(src_root=str(tmp_path))) == []


def test_hskill001_quiet_on_paths_in_code_fences_and_urls(tmp_path: Path) -> None:
    """A skill documenting a bad path, or quoting a traceback, is teaching."""
    make_skill(
        tmp_path,
        "a",
        "name: a\ndescription: Use when testing.",
        "## What NOT to do\n\n```\n/Users/alice/Documents/thing.md\n```\n\n"
        "See https://example.com/home/getting-started for background.\n"
        "The Docker workdir is always /home/app which is fine.\n"
        "More body text to satisfy length.\n",
    )
    assert "HSKILL-001" not in codes(SkillPortabilityCheck().run(src_root=str(tmp_path)))


def test_hskill001_reports_the_true_line_number(tmp_path: Path) -> None:
    """Line numbers were short by the frontmatter length."""
    make_skill(
        tmp_path,
        "a",
        "name: a\ndescription: Use when testing.",
        "line one\nline two\nsee /Users/bob/secret/notes.md here\nline four\nline five\n",
    )
    result = SkillPortabilityCheck().run(src_root=str(tmp_path))
    hits = [v for v in [*result.violations, *result.warnings] if v.code == "HSKILL-001"]
    assert hits and hits[0].line == 8, [(v.line, v.message) for v in hits]


def test_hskill002_accepts_documented_spec_fields(tmp_path: Path) -> None:
    """`model`, `argument-hint` and `context` are in the published spec."""
    make_skill(
        tmp_path,
        "a",
        "name: a\ndescription: Use when testing.\nmodel: opus\n"
        'argument-hint: "[file-path]"\ncontext: fresh',
    )
    assert "HSKILL-002" not in codes(SkillPortabilityCheck().run(src_root=str(tmp_path)))


def test_hskill003_allows_a_codex_only_superset(tmp_path: Path) -> None:
    """Extra Codex-side skills are a deliberate layout, not drift."""
    make_skill(tmp_path, "shared", "name: shared\ndescription: Use when testing.")
    (tmp_path / ".agents/skills/shared").mkdir(parents=True)
    (tmp_path / ".agents/skills/codex-only").mkdir(parents=True)
    assert "HSKILL-003" not in codes(SkillPortabilityCheck().run(src_root=str(tmp_path)))


def test_tensors_quiet_on_jaxtyping_and_einops(tmp_path: Path) -> None:
    write(
        tmp_path,
        "m.py",
        "from jaxtyping import Float\nfrom torch import Tensor\nfrom einops import rearrange\n\n"
        'def f(x: Float[Tensor, "b s d"], v: Float[Tensor, "d"]) -> Float[Tensor, "b s"]:\n'
        '    return rearrange(x, "b s d -> b d s")\n',
    )
    assert codes(TensorsCheck().run(src_root=str(tmp_path))) == []


def test_tensors_quiet_on_non_tensor_code(tmp_path: Path) -> None:
    """Ordinary Python must not attract tensor rules."""
    write(
        tmp_path,
        "m.py",
        "def add(a: int, b: int) -> int:\n    return a + b\n\n"
        "def name(items: list[str]) -> str:\n    return items[0]\n",
    )
    assert codes(TensorsCheck().run(src_root=str(tmp_path))) == []


def test_tensors_survives_unparseable_file(tmp_path: Path) -> None:
    write(tmp_path, "broken.py", "def f(:\n")
    assert codes(TensorsCheck().run(src_root=str(tmp_path))) == []


# --------------------------------------------------------------------------
# Skill portability
# --------------------------------------------------------------------------


def test_hskill001_fires_on_machine_path(tmp_path: Path) -> None:
    make_skill(
        tmp_path,
        "a",
        "name: a\ndescription: Use when testing.",
        SKILL_BODY + "\nSee /Users/someone/thing.md\n",
    )
    assert "HSKILL-001" in codes(SkillPortabilityCheck().run(src_root=str(tmp_path)))


def test_task_style_descriptions_are_not_flagged(tmp_path: Path) -> None:
    """Regression: a rule requiring literal 'use when' phrasing produced 43
    findings and zero true positives across four real skill collections. An
    imperative task description says when to use a skill perfectly well."""
    for i, description in enumerate(
        [
            "Convert a Jupyter notebook (.ipynb) to a marimo notebook (.py).",
            "Generate anywidget components for marimo notebooks.",
            "Check if a marimo notebook is compatible with WASM and report issues.",
        ]
    ):
        make_skill(tmp_path, f"s{i}", f"name: s{i}\ndescription: {description}")
    (tmp_path / ".agents").mkdir()
    (tmp_path / ".agents/skills").symlink_to(
        Path("..") / ".claude" / "skills", target_is_directory=True
    )
    assert codes(SkillPortabilityCheck().run(src_root=str(tmp_path))) == []


def test_hskill002_fires_on_unknown_key(tmp_path: Path) -> None:
    make_skill(tmp_path, "a", "name: a\ndescription: Use when testing.\ndescriptn: typo")
    assert "HSKILL-002" in codes(SkillPortabilityCheck().run(src_root=str(tmp_path)))


def test_hskill003_fires_when_link_is_a_text_file(tmp_path: Path) -> None:
    """Git on Windows checks a symlink out as text; Codex then sees no skills."""
    make_skill(tmp_path, "a", "name: a\ndescription: Use when testing.")
    write(tmp_path, ".agents/skills", "../.claude/skills")
    assert "HSKILL-003" in codes(SkillPortabilityCheck().run(src_root=str(tmp_path)))


def test_hskill003_fires_when_copy_has_drifted(tmp_path: Path) -> None:
    make_skill(tmp_path, "a", "name: a\ndescription: Use when testing.")
    make_skill(tmp_path, "b", "name: b\ndescription: Use when testing.")
    (tmp_path / ".agents").mkdir()
    (tmp_path / ".agents/skills/a").mkdir(parents=True)
    assert "HSKILL-003" in codes(SkillPortabilityCheck().run(src_root=str(tmp_path)))


def test_codex_link_check_can_be_disabled(tmp_path: Path) -> None:
    make_skill(tmp_path, "a", "name: a\ndescription: Use when testing.")
    check = SkillPortabilityCheck()
    check.configure(settings={"check_codex_skills": False})
    assert codes(check.run(src_root=str(tmp_path))) == []


def test_hskill003_quiet_when_symlinked(tmp_path: Path) -> None:
    make_skill(tmp_path, "a", "name: a\ndescription: Use when testing.")
    (tmp_path / ".agents").mkdir()
    (tmp_path / ".agents/skills").symlink_to(
        Path("..") / ".claude" / "skills", target_is_directory=True
    )
    assert "HSKILL-003" not in codes(SkillPortabilityCheck().run(src_root=str(tmp_path)))


def test_skill_checks_quiet_on_a_well_formed_skill(tmp_path: Path) -> None:
    """The whole point: a correct skill produces nothing at all."""
    make_skill(tmp_path, "good", "name: good\ndescription: Use when the user asks for a thing.")
    (tmp_path / ".agents").mkdir()
    (tmp_path / ".agents/skills").symlink_to(
        Path("..") / ".claude" / "skills", target_is_directory=True
    )
    assert codes(SkillPortabilityCheck().run(src_root=str(tmp_path))) == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
