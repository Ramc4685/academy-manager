"""read_level_names: no single active program is a quiet state, a fault still warns."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest

from backend.v2.contexts.curriculum.application.errors import (
    MultipleActivePrograms,
    NoActiveProgram,
)
from backend.v2.interfaces.coach.today_routes import read_level_names


def _use_cases(error: Exception) -> SimpleNamespace:
    async def resolve() -> object:
        raise error

    return SimpleNamespace(
        student_progress=SimpleNamespace(get_active_level_names=None),
        curriculum=SimpleNamespace(resolve_default_program=SimpleNamespace(execute=resolve)),
    )


@pytest.mark.parametrize("error", [NoActiveProgram(), MultipleActivePrograms()])
def test_no_single_program_hides_levels_without_a_warning(error, caplog) -> None:
    with caplog.at_level(logging.WARNING):
        assert asyncio.run(read_level_names(_use_cases(error), ["kid-1"])) == {}  # type: ignore[arg-type]
    assert caplog.records == []


def test_an_unexpected_failure_still_warns(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        assert asyncio.run(read_level_names(_use_cases(RuntimeError("boom")), ["kid-1"])) == {}  # type: ignore[arg-type]
    assert any("level lookup failed" in r.message for r in caplog.records)
