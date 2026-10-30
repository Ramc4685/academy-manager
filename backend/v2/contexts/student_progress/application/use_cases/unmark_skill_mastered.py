"""Use case: coach takes back a mistaken "got it" tap.

The skill drops back to PRACTICING and any level-up still waiting for the
evening auto-approval is withdrawn, so undo is complete as long as it lands
before ``AutoApproveLevelUps`` runs. Only the active level's skills can be
undone: a completed level's skills belong to an issued certificate.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel

from backend.v2.contexts.student_progress.application.ports import (
    LevelUpRecommendationRepository,
    SkillLookup,
    StudentLevelProgressRepository,
    StudentSkillProgressRepository,
)
from backend.v2.contexts.student_progress.domain.errors import (
    LevelUpInProgress,
    SkillNotOnCurrentLevel,
    SkillProgressNotFound,
    StudentNotPlaced,
)
from backend.v2.contexts.student_progress.domain.events import (
    SkillStatusUpdated,
    SkillStatusUpdatedPayload,
)
from backend.v2.shared.events import Outbox
from backend.v2.shared.tenancy import current_academy_id

UNDONE_BY_COACH_REASON = "undone_by_coach"


class UnmarkSkillMasteredCommand(BaseModel):
    model_config = {"frozen": True}
    student_id: str
    skill_id: str
    program_id: str
    updated_by: str


class UnmarkSkillMasteredResult(BaseModel):
    model_config = {"frozen": True}
    student_id: str
    skill_id: str
    status: str
    withdrawn_rec_ids: list[str]


class UnmarkSkillMastered:
    def __init__(
        self,
        *,
        level_progress: StudentLevelProgressRepository,
        skill_progress: StudentSkillProgressRepository,
        recommendations: LevelUpRecommendationRepository,
        skill_lookup: SkillLookup,
        outbox: Outbox | None = None,
    ) -> None:
        self._level_progress = level_progress
        self._skill_progress = skill_progress
        self._recs = recommendations
        self._skill_lookup = skill_lookup
        self._outbox = outbox

    async def execute(self, cmd: UnmarkSkillMasteredCommand) -> UnmarkSkillMasteredResult:
        active = await self._level_progress.get_active(cmd.student_id, cmd.program_id)
        if active is None:
            raise StudentNotPlaced(
                "student has no active level", student_id=cmd.student_id, program_id=cmd.program_id
            )
        skill = await self._skill_lookup.get_skill(cmd.skill_id)
        if getattr(skill, "level_id", None) != active.level_id:
            raise SkillNotOnCurrentLevel(
                "only skills on the student's current level can be undone",
                student_id=cmd.student_id,
                skill_id=cmd.skill_id,
            )
        existing = await self._skill_progress.get(cmd.student_id, cmd.skill_id)
        if existing is None:
            raise SkillProgressNotFound(
                "skill has no progress to undo", student_id=cmd.student_id, skill_id=cmd.skill_id
            )

        now = datetime.now(UTC)
        withdrawn: list[str] = []
        # The withdrawal must win before the skill is demoted: a level-up the
        # owner or the evening job is already approving (APPROVING) would
        # otherwise certify a level with this skill back at PRACTICING.
        pending = await self._recs.get_active_for_student(cmd.student_id, cmd.program_id)
        # A REJECTING row ends rejected anyway, so it does not block the undo.
        if (
            pending is not None
            and pending.from_level_id == active.level_id
            and pending.status != "REJECTING"
        ):
            if pending.status != "RECOMMENDED" or not await self._recs.update_status(
                pending.rec_id,
                "REJECTED",
                cmd.updated_by,
                now,
                UNDONE_BY_COACH_REASON,
                expected_status="RECOMMENDED",
            ):
                raise LevelUpInProgress(
                    "this level-up is already being approved; undo it from the owner queue",
                    student_id=cmd.student_id,
                    rec_id=pending.rec_id,
                )
            withdrawn.append(pending.rec_id)

        if existing.status != "PASSED":
            return UnmarkSkillMasteredResult(
                student_id=cmd.student_id,
                skill_id=cmd.skill_id,
                status=existing.status,
                withdrawn_rec_ids=withdrawn,
            )

        updated = existing.model_copy(
            update={
                "status": "PRACTICING",
                "last_updated_at": now,
                "last_updated_by": cmd.updated_by,
            }
        )
        persisted = await self._skill_progress.upsert(updated)
        if self._outbox is not None:
            await self._outbox.append(
                SkillStatusUpdated(
                    aggregate_id=persisted.skill_progress_id,
                    academy_id=current_academy_id(),
                    payload=SkillStatusUpdatedPayload(
                        student_id=cmd.student_id,
                        skill_id=cmd.skill_id,
                        level_id=active.level_id,
                        old_status="PASSED",
                        new_status="PRACTICING",
                        updated_by=cmd.updated_by,
                    ),
                )
            )
        return UnmarkSkillMasteredResult(
            student_id=cmd.student_id,
            skill_id=cmd.skill_id,
            status="PRACTICING",
            withdrawn_rec_ids=withdrawn,
        )
