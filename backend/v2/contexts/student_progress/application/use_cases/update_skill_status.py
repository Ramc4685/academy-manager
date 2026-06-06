"""Use case: coach updates a student's skill status."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel

from backend.v2.contexts.student_progress.application.ports import (
    StudentLevelProgressRepository,
    StudentSkillProgressRepository,
)
from backend.v2.contexts.student_progress.domain.errors import (
    SkillAlreadyPassed,
    StudentNotPlaced,
)
from backend.v2.contexts.student_progress.domain.events import (
    SkillStatusUpdated,
    SkillStatusUpdatedPayload,
)
from backend.v2.contexts.student_progress.domain.models import (
    StudentSkillProgress,
)
from backend.v2.shared.events import Outbox
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy import TenantContextUnset, current_academy_id

# Statuses a coach can set (cannot set PASSED directly — use RecordTestAttempt)
CoachSettableStatus = Literal["INTRODUCED", "LEARNING", "PRACTICING", "TEST_READY", "NEEDS_REVIEW"]


def _resolve_academy_id() -> str:
    try:
        return current_academy_id()
    except TenantContextUnset:
        return ""


class UpdateSkillStatusCommand(BaseModel):
    model_config = {"frozen": True}
    student_id: str
    skill_id: str
    level_id: str
    program_id: str
    new_status: CoachSettableStatus
    updated_by: str


class UpdateSkillStatus:
    def __init__(
        self,
        *,
        level_progress: StudentLevelProgressRepository,
        skill_progress: StudentSkillProgressRepository,
        outbox: Outbox | None = None,
    ) -> None:
        self._level_progress = level_progress
        self._skill_progress = skill_progress
        self._outbox = outbox

    async def execute(self, cmd: UpdateSkillStatusCommand) -> StudentSkillProgress:
        # Verify student has an active level
        active = await self._level_progress.get_active(cmd.student_id, cmd.program_id)
        if active is None:
            raise StudentNotPlaced(
                "student has no active level in this program",
                student_id=cmd.student_id,
                program_id=cmd.program_id,
            )

        existing = await self._skill_progress.get(cmd.student_id, cmd.skill_id)
        if existing and existing.status == "PASSED":
            raise SkillAlreadyPassed(
                "skill is already passed; use needs_review to flag regression",
                student_id=cmd.student_id,
                skill_id=cmd.skill_id,
            )

        now = datetime.now(UTC)
        if existing is None:
            updated = StudentSkillProgress(
                skill_progress_id=str(new_ulid()),
                academy_id="",
                student_id=cmd.student_id,
                skill_id=cmd.skill_id,
                level_id=cmd.level_id,
                program_id=cmd.program_id,
                status=cmd.new_status,
                introduced_at=now if cmd.new_status == "INTRODUCED" else None,
                last_updated_at=now,
                last_updated_by=cmd.updated_by,
            )
        else:
            updated = existing.model_copy(
                update={
                    "status": cmd.new_status,
                    "introduced_at": existing.introduced_at
                    or (now if cmd.new_status == "INTRODUCED" else None),
                    "last_updated_at": now,
                    "last_updated_by": cmd.updated_by,
                }
            )
        persisted = await self._skill_progress.upsert(updated)

        if self._outbox is not None:
            await self._outbox.append(
                SkillStatusUpdated(
                    aggregate_id=persisted.skill_progress_id,
                    academy_id=_resolve_academy_id(),
                    payload=SkillStatusUpdatedPayload(
                        student_id=cmd.student_id,
                        skill_id=cmd.skill_id,
                        level_id=cmd.level_id,
                        old_status=existing.status if existing is not None else "NONE",
                        new_status=cmd.new_status,
                        updated_by=cmd.updated_by,
                    ),
                )
            )

        return persisted
