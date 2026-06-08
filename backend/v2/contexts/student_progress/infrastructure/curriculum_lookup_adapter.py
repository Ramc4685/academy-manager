"""Adapter: reads curriculum data for student progress use cases."""

from __future__ import annotations

from typing import Any


class CurriculumSkillLookupAdapter:
    """Reads skill/level data from curriculum repositories.

    Does not import curriculum domain models — keeps contexts decoupled.
    Uses duck-typing: skill objects are returned as-is from curriculum repos.
    """

    def __init__(self, *, skill_repo: Any, level_repo: Any) -> None:
        self._skills = skill_repo
        self._levels = level_repo

    async def get_skill(self, skill_id: str) -> Any | None:
        return await self._skills.get(skill_id)

    async def get_level(self, level_id: str) -> Any | None:
        return await self._levels.get(level_id)

    async def list_skills_for_level(self, level_id: str) -> list[Any]:
        return await self._skills.list_for_level(level_id)

    async def get_next_level(self, program_id: str, current_sequence: int) -> Any | None:
        all_levels = await self._levels.list_for_program(program_id)
        next_levels = [
            lvl for lvl in all_levels if getattr(lvl, "sequence", 0) == current_sequence + 1
        ]
        return next_levels[0] if next_levels else None
