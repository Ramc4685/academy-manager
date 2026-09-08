"""Use case: get the queue of students ready for level-up."""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.v2.contexts.student_progress.application.ports import (
    EnrollmentStatusLookup,
    LevelUpRecommendationRepository,
    SkillLookup,
    StudentLevelProgressRepository,
    StudentSkillProgressRepository,
)
from backend.v2.contexts.student_progress.domain.models import LevelUpRecommendation


@dataclass(frozen=True)
class GetLevelUpQueueCommand:
    program_id: str | None = field(default=None)


class LevelUpQueueEntry(LevelUpRecommendation):
    """A pending recommendation plus what the admin needs to decide it.

    ``enrollment_active`` is False when the student no longer holds a live
    (active or paused) enrollment (issue #673). The row is still listed so the
    admin can reject it; approval is refused server-side either way.
    """

    enrollment_active: bool = True


class GetLevelUpQueue:
    def __init__(
        self,
        *,
        level_progress: StudentLevelProgressRepository,
        skill_progress: StudentSkillProgressRepository,
        recommendations: LevelUpRecommendationRepository,
        skill_lookup: SkillLookup,
        enrollment_lookup: EnrollmentStatusLookup,
    ) -> None:
        self._level_progress = level_progress
        self._skill_progress = skill_progress
        self._recs = recommendations
        self._skill_lookup = skill_lookup
        self._enrollments = enrollment_lookup

    async def execute(self, cmd: GetLevelUpQueueCommand) -> list[LevelUpQueueEntry]:
        pending = await self._recs.list_pending()
        if cmd.program_id is not None:
            pending = [rec for rec in pending if rec.program_id == cmd.program_id]
        # One batch read for the whole queue rather than a lookup per row.
        student_ids = sorted({rec.student_id for rec in pending})
        live = await self._enrollments.students_with_active_or_paused_enrollment(student_ids)
        return [
            LevelUpQueueEntry(**rec.model_dump(), enrollment_active=rec.student_id in live)
            for rec in pending
        ]
