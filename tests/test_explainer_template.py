"""The explainer page's JavaScript parses, and its highlight anchoring behaves.

The page is a single self-contained HTML file with no build step, so nothing else
in the pipeline would notice a syntax error in it — `build-explainer` would write
a 12 MB page that dies on load. This runs the checks node can make.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SUITE = Path(__file__).parent / "explainer_template.test.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_page_script_parses_and_anchors_correctly() -> None:
    result = subprocess.run(
        [shutil.which("node") or "node", str(SUITE)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
