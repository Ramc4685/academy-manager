"""Read-side use cases for lesson cards."""

from __future__ import annotations

from dataclasses import dataclass

from backend.v2.contexts.curriculum.application.ports import LessonCardRepository
from backend.v2.contexts.curriculum.domain.models import LessonCard


@dataclass
class ListLessonCards:
    cards: LessonCardRepository

    async def execute(self, program_id: str) -> list[LessonCard]:
        return await self.cards.list_for_program(program_id)


@dataclass
class GetLessonCardForSkill:
    cards: LessonCardRepository

    async def execute(self, skill_id: str) -> LessonCard | None:
        """Return the lesson card for a skill.

        A skill may appear on more than one card; pick the lowest
        ``display_order`` and break ties on ``lesson_number`` for a stable,
        deterministic result.
        """
        matches = await self.cards.list_for_skill(skill_id)
        if not matches:
            return None
        return sorted(matches, key=lambda c: (c.display_order, c.lesson_number))[0]
