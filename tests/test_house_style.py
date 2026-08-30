"""The vendored font, and the one way it fails quietly."""

from __future__ import annotations

import warnings

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

from odd_number.visualisations.figures import (  # noqa: E402
    FONT_DIR,
    FONT_FAMILY,
    FONT_STACK,
    apply_house_style,
)


def test_the_font_files_travel_with_the_repository() -> None:
    """`figures/` is committed, so a checkout has to be able to rebuild it."""
    names = sorted(p.name for p in FONT_DIR.glob("*.ttf"))
    assert names == ["OpenSans-Bold.ttf", "OpenSans-Regular.ttf", "OpenSans-SemiBold.ttf"]
    assert (FONT_DIR / "LICENSE.txt").is_file(), "OFL-1.1 requires the licence to travel too"


def test_applying_the_style_resolves_to_the_vendored_face() -> None:
    apply_house_style()
    for weight in ("normal", "bold"):
        found = font_manager.findfont(
            font_manager.FontProperties(family=FONT_FAMILY, weight=weight)
        )
        assert "OpenSans" in found, f"{weight} did not resolve to the vendored font: {found}"


def test_the_stack_ends_somewhere_matplotlib_always_has() -> None:
    """A checkout without the font files must still draw rather than raise."""
    assert FONT_STACK[-1] == "DejaVu Sans"


def test_a_glyph_the_font_lacks_is_caught_here_rather_than_shipped() -> None:
    """Open Sans has no arrows. A missing glyph only warns, so it is easy to ship
    a figure with a blank box in it; this turns that warning into a failure."""
    apply_house_style()
    figure, axes = plt.subplots()
    axes.set_title("← an arrow Open Sans does not have")
    with warnings.catch_warnings():
        warnings.simplefilter("error", UserWarning)
        try:
            figure.canvas.draw()
        except UserWarning as exc:
            assert "missing from font" in str(exc)
        else:
            raise AssertionError("expected a missing-glyph warning and got none")
    plt.close(figure)
