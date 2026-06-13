"""Use case: parent-safe recent skill updates for one student."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from backend.v2.contexts.student_progress.application.ports import (
    SkillLookup,
    StudentSkillProgressRepository,
)
from backend.v2.contexts.student_progress.domain.models import SkillStatus


class RecentSkillUpdate(BaseModel):
    model_config = {"frozen": True}

    skill_id: str
    skill_name: str
    status: SkillStatus
    updated_at: datetime


class GetRecentSkillUpdates:
    def __init__(
        self,
        *,
        skill_progress: StudentSkillProgressRepository,
        skill_lookup: SkillLookup,
    ) -> None:
        self._skill_progress = skill_progress
        self._skill_lookup = skill_lookup

    async def execute(self, student_id: str, *, limit: int = 10) -> list[RecentSkillUpdate]:
        rows = await self._skill_progress.list_recent_for_student(student_id, limit=limit)
        sorted_rows = sorted(rows, key=lambda row: row.last_updated_at, reverse=True)

        updates: list[RecentSkillUpdate] = []
        for row in sorted_rows:
            skill = await self._skill_lookup.get_skill(row.skill_id)
            updates.append(
                RecentSkillUpdate(
                    skill_id=row.skill_id,
                    skill_name=str(getattr(skill, "name", row.skill_id)),
                    status=row.status,
                    updated_at=row.last_updated_at,
                )
            )
        return updates
