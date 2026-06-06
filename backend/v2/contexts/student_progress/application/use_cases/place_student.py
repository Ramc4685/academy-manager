"""Use case: place a student in a program level."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel

from backend.v2.contexts.student_progress.application.ports import (
    SkillLookup,
    StudentLevelProgressRepository,
    StudentSkillProgressRepository,
)
from backend.v2.contexts.student_progress.domain.events import (
    StudentPlacedInLevel,
    StudentPlacedInLevelPayload,
)
from backend.v2.contexts.student_progress.domain.models import (
    StudentLevelProgress,
    StudentSkillProgress,
)
from backend.v2.shared.events import Outbox
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy import TenantContextUnset, current_academy_id


def _resolve_academy_id() -> str:
    """Best-effort tenant id for the emitted event.

    Persisted documents are tenant-scoped by the repository regardless; this
    only carries the academy onto the event when the tenant ContextVar is set.
    """
    try:
        return current_academy_id()
    except TenantContextUnset:
        return ""


class PlaceStudentInLevelCommand(BaseModel):
    model_config = {"frozen": True}
    student_id: str
    program_id: str
    level_id: str
    placed_by: str


class PlaceStudentInLevel:
    def __init__(
        self,
        *,
        level_progress: StudentLevelProgressRepository,
        skill_progress: StudentSkillProgressRepository,
        skill_lookup: SkillLookup,
        outbox: Outbox | None = None,
    ) -> None:
        self._level_progress = level_progress
        self._skill_progress = skill_progress
        self._skill_lookup = skill_lookup
        self._outbox = outbox

    async def execute(self, cmd: PlaceStudentInLevelCommand) -> StudentLevelProgress:
        now = datetime.now(UTC)
        progress = StudentLevelProgress(
            progress_id=str(new_ulid()),
            academy_id="",  # injected by repo
            student_id=cmd.student_id,
            program_id=cmd.program_id,
            level_id=cmd.level_id,
            status="active",
            started_at=now,
            completed_at=None,
            created_at=now,
        )
        await self._level_progress.save(progress)

        # Create NOT_STARTED skill progress records for all skills in this level
        skills = await self._skill_lookup.list_skills_for_level(cmd.level_id)
        for skill in skills:
            skill_prog = StudentSkillProgress(
                skill_progress_id=str(new_ulid()),
                academy_id="",  # injected by repo
                student_id=cmd.student_id,
                skill_id=skill.skill_id,  # type: ignore[attr-defined]
                level_id=cmd.level_id,
                program_id=cmd.program_id,
                status="NOT_STARTED",
                introduced_at=None,
                last_updated_at=now,
                last_updated_by=cmd.placed_by,
            )
            await self._skill_progress.upsert(skill_prog)

        if self._outbox is not None:
            await self._outbox.append(
                StudentPlacedInLevel(
                    aggregate_id=progress.progress_id,
                    academy_id=_resolve_academy_id(),
                    payload=StudentPlacedInLevelPayload(
                        student_id=cmd.student_id,
                        program_id=cmd.program_id,
                        level_id=cmd.level_id,
                        progress_id=progress.progress_id,
                    ),
                )
            )

        return progress
