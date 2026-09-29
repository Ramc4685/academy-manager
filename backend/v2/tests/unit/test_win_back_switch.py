"""The per-academy win-back switch reads ``notifications.win_back_enabled``
(hardcoded-values row 10). Absent means on, so BLNO keeps sending."""

from __future__ import annotations

from typing import Any

import pytest

from backend.v2.composition.win_back import AcademyWinBackSwitch

pytestmark = pytest.mark.asyncio


class _Academies:
    def __init__(self, docs: dict[str, dict[str, Any]]) -> None:
        self._docs = docs
        self.asked: list[str] = []

    async def find_by_id(self, academy_id: str) -> dict[str, Any] | None:
        self.asked.append(academy_id)
        return self._docs.get(academy_id)


async def test_absent_setting_is_on() -> None:
    academies = _Academies(
        {
            "blno": {"academy_id": "blno", "notifications": {"daily_digest_to_admin": False}},
            "bare": {"academy_id": "bare"},
        }
    )
    switch = AcademyWinBackSwitch(academies)
    assert await switch.is_enabled("blno") is True
    assert await switch.is_enabled("bare") is True


async def test_explicit_values() -> None:
    academies = _Academies(
        {
            "off": {"notifications": {"win_back_enabled": False}},
            "on": {"notifications": {"win_back_enabled": True}},
        }
    )
    switch = AcademyWinBackSwitch(academies)
    assert await switch.is_enabled("off") is False
    assert await switch.is_enabled("on") is True


async def test_reads_only_the_asked_academy() -> None:
    academies = _Academies(
        {"a": {"notifications": {"win_back_enabled": False}}, "b": {"notifications": {}}}
    )
    assert await AcademyWinBackSwitch(academies).is_enabled("b") is True
    assert academies.asked == ["b"]


async def test_academy_without_a_document_keeps_todays_behaviour() -> None:
    # The scheduler also runs the deployment's default academy id, which may
    # have no academy document; it sent win-back before the switch existed.
    assert await AcademyWinBackSwitch(_Academies({})).is_enabled("missing") is True


async def test_failed_read_skips_the_tick() -> None:
    # A later daily tick retries: a due milestone stays due for 30 days.

    class _Broken:
        async def find_by_id(self, academy_id: str) -> Any:
            raise RuntimeError("down")

    assert await AcademyWinBackSwitch(_Broken()).is_enabled("a") is False
