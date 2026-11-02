"""Default level colours: readable labels, distinct in grayscale, sane fallbacks."""

from __future__ import annotations

from datetime import UTC, datetime
from itertools import pairwise

import pytest
from backend.v2.contexts.curriculum.domain.models import (
    DEFAULT_LEVEL_COLORS,
    Level,
    _relative_luminance,
    default_level_color,
    level_label_color,
)
from pydantic import ValidationError


def _contrast(a: str, b: str) -> float:
    la, lb = sorted((_relative_luminance(a), _relative_luminance(b)))
    return (lb + 0.05) / (la + 0.05)


def _l_star(hex_color: str) -> float:
    y = _relative_luminance(hex_color)
    return 116 * y ** (1 / 3) - 16 if y > 0.008856 else 903.3 * y


def test_each_default_passes_aa_with_its_label() -> None:
    for _name, hex_color in DEFAULT_LEVEL_COLORS:
        assert _contrast(hex_color, level_label_color(hex_color)) >= 4.5, hex_color


def test_defaults_step_apart_in_grayscale() -> None:
    lightness = [_l_star(h) for _, h in DEFAULT_LEVEL_COLORS]
    assert lightness == sorted(lightness, reverse=True)
    assert min(a - b for a, b in pairwise(lightness)) >= 10


@pytest.mark.parametrize("hex_color", ["#777777", "#808080", "#FF0000", "#00FF00", "#0EA5E9"])
def test_any_custom_colour_gets_an_aa_label(hex_color: str) -> None:
    assert _contrast(hex_color, level_label_color(hex_color)) >= 4.5


def test_sequence_maps_to_palette_and_top_levels_stay_black() -> None:
    assert default_level_color(1) == "#FDE047"
    assert default_level_color(4) == "#2563EB"
    assert default_level_color(9) == default_level_color(6) == "#111827"


def _level(**kw: object) -> Level:
    now = datetime(2026, 11, 2, tzinfo=UTC)
    base: dict[str, object] = {
        "level_id": "L",
        "program_id": "P",
        "academy_id": "A",
        "sequence": 2,
        "name": "Net",
        "created_at": now,
        "updated_at": now,
        "created_by": "o",
    }
    return Level(**(base | kw))  # type: ignore[arg-type]


def test_display_color_falls_back_and_is_serialised() -> None:
    assert _level().display_color == "#FB923C"
    assert _level(color="#0EA5E9").model_dump()["display_color"] == "#0EA5E9"
    with pytest.raises(ValidationError):
        _level(color="javascript:alert(1)")
