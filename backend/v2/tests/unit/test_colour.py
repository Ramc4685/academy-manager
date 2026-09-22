"""WCAG contrast primitives and the readable-text-on-brand_color rule."""

from __future__ import annotations

import pytest

from backend.v2.shared.comms import colour as c

# Matches the ticket's matrix plus one colour in the band where neither white
# nor ink passes at the raw value, so the nudge branch is exercised.
LIGHT = ["#FFD400", "#F5F5F5", "#facc15"]
DARK = ["#1F2937", "#000000", "#2563eb"]
MID = ["#808080", "#3B82F6", "#E11D48"]
FAILING_BAND = ["#7a7a7a", "#777777", "#7f7f7f"]


def test_contrast_ratio_reference_values() -> None:
    assert c.contrast_ratio("#ffffff", "#000000") == pytest.approx(21.0)
    assert c.contrast_ratio("#ffffff", "#ffffff") == pytest.approx(1.0)
    assert c.contrast_ratio("#000000", "#ffffff") == c.contrast_ratio("#ffffff", "#000000")
    assert c.contrast_ratio("#abc", "#aabbcc") == pytest.approx(1.0)


def test_relative_luminance_endpoints() -> None:
    assert c.relative_luminance("#000000") == 0
    assert c.relative_luminance("#ffffff") == pytest.approx(1.0)


@pytest.mark.parametrize("fill", LIGHT + DARK + MID + FAILING_BAND)
def test_readable_pair_meets_aa(fill: str) -> None:
    background, text = c.readable_button_colors(fill)
    assert c.contrast_ratio(text, background) >= c.AA_TEXT
    assert text in {c.WHITE, c.INK}


@pytest.mark.parametrize("fill", LIGHT)
def test_light_fills_keep_background_and_use_ink(fill: str) -> None:
    assert c.readable_button_colors(fill) == (fill.lower(), c.INK)


@pytest.mark.parametrize("fill", DARK)
def test_dark_fills_keep_background_and_use_white(fill: str) -> None:
    assert c.readable_button_colors(fill) == (fill.lower(), c.WHITE)


def test_mid_tones_resolve_without_adjustment() -> None:
    assert c.readable_button_colors("#808080") == ("#808080", c.INK)
    assert c.readable_button_colors("#3B82F6") == ("#3b82f6", c.INK)
    assert c.readable_button_colors("#E11D48") == ("#e11d48", c.WHITE)


@pytest.mark.parametrize("fill", FAILING_BAND)
def test_failing_band_nudges_background(fill: str) -> None:
    # Neither text colour passes at the raw value...
    assert c.contrast_ratio(c.WHITE, fill) < c.AA_TEXT
    assert c.contrast_ratio(c.INK, fill) < c.AA_TEXT
    background, text = c.readable_button_colors(fill)
    # ...so the fill moves, only as far as needed, and the pair passes.
    assert background != fill
    assert c.contrast_ratio(text, background) >= c.AA_TEXT
    assert c.contrast_ratio(text, background) < c.AA_TEXT + 0.6


def test_nudge_direction_follows_nearer_text_colour() -> None:
    # #7a7a7a: white 4.29 vs ink 4.16 -> keep white, darken the fill toward ink.
    bg, text = c.readable_button_colors("#7a7a7a")
    assert text == c.WHITE
    assert c.relative_luminance(bg) < c.relative_luminance("#7a7a7a")
    # #7f7f7f: white 4.00 vs ink 4.46 -> keep ink, lighten the fill toward white.
    bg, text = c.readable_button_colors("#7f7f7f")
    assert text == c.INK
    assert c.relative_luminance(bg) > c.relative_luminance("#7f7f7f")


@pytest.mark.parametrize("bad", ["red", "#12", "", "ffd400", "#ggg", None])
def test_invalid_hex_raises(bad: object) -> None:
    with pytest.raises(ValueError):
        c.readable_button_colors(bad)  # type: ignore[arg-type]
