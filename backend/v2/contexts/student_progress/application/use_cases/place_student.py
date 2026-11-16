"""Use case: place a student in a program level."""

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
    LevelNotConfigured,
    LevelUpInProgress,
    SkillNotOnCurrentLevel,
)
from backend.v2.contexts.student_progress.domain.events import (
    StudentPlacedInLevel,
    StudentPlacedInLevelPayload,
)
from backend.v2.contexts.student_progress.domain.logic import check_level_completion
from backend.v2.contexts.student_progress.domain.models import (
    StudentLevelProgress,
    StudentSkillProgress,
)
from backend.v2.shared.events import Outbox
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy import TenantContextUnset, current_academy_id

#: Why a pending level-up was closed: the owner moved the student by hand.
SUPERSEDED_BY_PLACEMENT_REASON = "superseded_by_placement"


def _resolve_academy_id() -> str:
    """Best-effort tenant id for the emitted event.

    Persisted documents are tenant-scoped by the repository regardless; this
    only carries the academy onto the event when the tenant ContextVar is set.
    """
    try:
        return current_academy_id()
    except TenantContextUnset:
        return ""


async def seed_level_skills(
    *,
    skill_progress: StudentSkillProgressRepository,
    skill_lookup: SkillLookup,
    student_id: str,
    program_id: str,
    level_id: str,
    actor: str,
    now: datetime,
) -> None:
    """NOT_STARTED rows for the level's skills the student has no row for yet.

    Insert-if-missing, never overwrite: a skill the student already earned
    (an earlier placement, a level they come back to) keeps its status.
    """
    for skill in await skill_lookup.list_skills_for_level(level_id):
        await skill_progress.insert_if_missing(
            StudentSkillProgress(
                skill_progress_id=str(new_ulid()),
                academy_id="",  # injected by repo
                student_id=student_id,
                skill_id=skill.skill_id,  # type: ignore[attr-defined]
                level_id=level_id,
                program_id=program_id,
                status="NOT_STARTED",
                introduced_at=None,
                last_updated_at=now,
                last_updated_by=actor,
            )
        )


class PlaceStudentInLevelCommand(BaseModel):
    model_config = {"frozen": True}
    student_id: str
    program_id: str
    level_id: str
    placed_by: str
    reason: str = "pathway_placement"
    #: Skills on the target level the student already has: marked PASSED
    #: without a test, and never queue a level-up.
    credited_skill_ids: list[str] = []
    #: False keeps credits out of the parents' evening wins (``silent``).
    notify_parents: bool = True


class PlaceStudentInLevel:
    def __init__(
        self,
        *,
        level_progress: StudentLevelProgressRepository,
        skill_progress: StudentSkillProgressRepository,
        skill_lookup: SkillLookup,
        recommendations: LevelUpRecommendationRepository,
        outbox: Outbox | None = None,
    ) -> None:
        self._level_progress = level_progress
        self._skill_progress = skill_progress
        self._skill_lookup = skill_lookup
        self._recs = recommendations
        self._outbox = outbox

    async def execute(self, cmd: PlaceStudentInLevelCommand) -> StudentLevelProgress:
        level = await self._skill_lookup.get_level(cmd.level_id)
        if (
            level is None
            or not getattr(level, "is_active", True)
            or getattr(level, "program_id", None) != cmd.program_id
        ):
            raise LevelNotConfigured(
                "level is missing, retired, or not in this program",
                level_id=cmd.level_id,
                program_id=cmd.program_id,
            )

        level_skill_ids = {
            s.skill_id  # type: ignore[attr-defined]
            for s in await self._skill_lookup.list_skills_for_level(cmd.level_id)
        }
        foreign = [sid for sid in cmd.credited_skill_ids if sid not in level_skill_ids]
        if foreign:
            raise SkillNotOnCurrentLevel(
                "credited skills must belong to the level the student is placed in",
                level_id=cmd.level_id,
                skill_ids=foreign,
            )

        now = datetime.now(UTC)
        active = await self._level_progress.get_active(cmd.student_id, cmd.program_id)
        if active is not None and active.level_id == cmd.level_id:
            # Skills added to the level since the student was placed need rows first.
            await seed_level_skills(
                skill_progress=self._skill_progress,
                skill_lookup=self._skill_lookup,
                student_id=cmd.student_id,
                program_id=cmd.program_id,
                level_id=cmd.level_id,
                actor=cmd.placed_by,
                now=now,
            )
            await self._credit(cmd, now)
            return active
        if active is not None:
            await self._withdraw_pending_level_up(cmd, now)
            if await self._level_finished(cmd.student_id, active.level_id):
                await self._level_progress.complete(active.progress_id, now)
            else:
                await self._level_progress.withdraw(active.progress_id, now)

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
        await seed_level_skills(
            skill_progress=self._skill_progress,
            skill_lookup=self._skill_lookup,
            student_id=cmd.student_id,
            program_id=cmd.program_id,
            level_id=cmd.level_id,
            actor=cmd.placed_by,
            now=now,
        )
        await self._credit(cmd, now)

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
                        placed_by=cmd.placed_by,
                        reason=cmd.reason,
                    ),
                )
            )

        return progress

    async def _withdraw_pending_level_up(
        self, cmd: PlaceStudentInLevelCommand, now: datetime
    ) -> None:
        """A level-up queued for the old level must not land after a re-placement.

        Same compare-and-set as the coach undo: an approval already claimed
        (APPROVING) wins, and the placement is refused rather than racing it.
        """
        pending = await self._recs.get_active_for_student(cmd.student_id, cmd.program_id)
        if pending is None or pending.status == "REJECTING":
            return
        if pending.status != "RECOMMENDED" or not await self._recs.update_status(
            pending.rec_id,
            "REJECTED",
            cmd.placed_by,
            now,
            SUPERSEDED_BY_PLACEMENT_REASON,
            expected_status="RECOMMENDED",
        ):
            raise LevelUpInProgress(
                "a level-up for this student is being approved; try again in a minute",
                student_id=cmd.student_id,
                rec_id=pending.rec_id,
            )

    async def _credit(self, cmd: PlaceStudentInLevelCommand, now: datetime) -> None:
        """Mark credited skills PASSED. Rows exist: the level was seeded first."""
        for skill_id in dict.fromkeys(cmd.credited_skill_ids):
            row = await self._skill_progress.get(cmd.student_id, skill_id)
            if row is None or row.status == "PASSED":
                continue
            await self._skill_progress.upsert(
                row.model_copy(
                    update={
                        "status": "PASSED",
                        "silent": not cmd.notify_parents,
                        "last_updated_at": now,
                        "last_updated_by": cmd.placed_by,
                    }
                )
            )

    async def _level_finished(self, student_id: str, level_id: str) -> bool:
        skills = await self._skill_lookup.list_skills_for_level(level_id)
        required = [s.skill_id for s in skills if getattr(s, "is_required", True)]  # type: ignore[attr-defined]
        passed = await self._skill_progress.list_passed_for_student_level(student_id, level_id)
        return check_level_completion(required, {p.skill_id for p in passed})
