"""Query: the name of each student's active level in a program (coach roster rows)."""

from __future__ import annotations

from collections.abc import Sequence

from backend.v2.contexts.student_progress.application.ports import (
    SkillLookup,
    StudentLevelProgressRepository,
)


class GetActiveLevelNames:
    def __init__(
        self, *, level_progress: StudentLevelProgressRepository, skill_lookup: SkillLookup
    ) -> None:
        self._level_progress = level_progress
        self._skill_lookup = skill_lookup

    async def execute(self, student_ids: Sequence[str], program_id: str) -> dict[str, str]:
        """``{student_id: level name}``; an unplaced student is left out."""
        if not student_ids:
            return {}
        rows = await self._level_progress.list_active_for_students(list(student_ids), program_id)
        names: dict[str, str] = {}
        for level_id in {row.level_id for row in rows}:
            level = await self._skill_lookup.get_level(level_id)
            names[level_id] = str(getattr(level, "name", "") or "") if level else ""
        return {row.student_id: names[row.level_id] for row in rows if names[row.level_id]}
