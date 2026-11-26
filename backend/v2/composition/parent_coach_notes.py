"""Parent read of a child's shared coach skill notes (S53, D-15).

Kept out of ``composition/parent.py`` (size cap). Wired onto
``app.state.parent_coach_notes`` in ``main.py``.
"""

from __future__ import annotations

from typing import Any

from backend.v2.contexts.coaching.application.use_cases.skill_notes import ListParentSkillNotes
from backend.v2.contexts.coaching.infrastructure.mongo_skill_note_repo import (
    MongoSkillNoteRepository,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_skill_repo import MongoSkillRepository


class _SkillNames:
    def __init__(self, skills: MongoSkillRepository) -> None:
        self._skills = skills

    async def names(self, skill_ids: list[str]) -> dict[str, str]:
        return {s.skill_id: s.name for s in await self._skills.list_by_ids(skill_ids)}


def compose_parent_coach_notes(db: Any) -> ListParentSkillNotes:
    return ListParentSkillNotes(
        notes=MongoSkillNoteRepository(db),
        skills=_SkillNames(MongoSkillRepository(db)),
    )
