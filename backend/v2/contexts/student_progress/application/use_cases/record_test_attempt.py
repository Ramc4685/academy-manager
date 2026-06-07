"""Use case: coach records a test attempt for a student skill."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from backend.v2.contexts.student_progress.application.ports import (
    SkillLookup,
    StudentLevelProgressRepository,
    StudentSkillProgressRepository,
    TestAttemptRepository,
)
from backend.v2.contexts.student_progress.domain.errors import (
    OverrideNotPermitted,
    StudentNotPlaced,
)
from backend.v2.contexts.student_progress.domain.events import (
    LevelCompleted,
    LevelCompletedPayload,
    SkillPassed,
    SkillPassedPayload,
    SkillTestAttempted,
    SkillTestAttemptedPayload,
)
from backend.v2.contexts.student_progress.domain.logic import (
    calculate_skill_pass,
    check_level_completion,
)
from backend.v2.contexts.student_progress.domain.models import (
    StudentSkillProgress,
    TestAttempt,
)
from backend.v2.shared.events import Outbox
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy import TenantContextUnset, current_academy_id


def _resolve_academy_id() -> str:
    try:
        return current_academy_id()
    except TenantContextUnset:
        return ""


class RecordTestAttemptCommand(BaseModel):
    model_config = {"frozen": True}
    student_id: str
    skill_id: str
    level_id: str
    program_id: str
    coach_id: str
    session_id: str | None = None
    occurrence_id: str | None = None
    scoring_type: str = "ATTEMPT_BASED"
    attempts_count: int = Field(ge=1)
    success_count: int = Field(ge=0)
    coach_override: bool = False
    override_reason: str | None = None
    notes: str = ""


class RecordTestAttemptResult(BaseModel):
    model_config = {"frozen": True}
    attempt_id: str
    passed: bool
    score: float
    skill_status: str
    level_completed: bool


class RecordTestAttempt:
    def __init__(
        self,
        *,
        level_progress: StudentLevelProgressRepository,
        skill_progress: StudentSkillProgressRepository,
        test_attempts: TestAttemptRepository,
        skill_lookup: SkillLookup,
        outbox: Outbox | None = None,
    ) -> None:
        self._level_progress = level_progress
        self._skill_progress = skill_progress
        self._test_attempts = test_attempts
        self._skill_lookup = skill_lookup
        self._outbox = outbox

    async def execute(self, cmd: RecordTestAttemptCommand) -> RecordTestAttemptResult:
        active = await self._level_progress.get_active(cmd.student_id, cmd.program_id)
        if active is None:
            raise StudentNotPlaced(
                "student has no active level",
                student_id=cmd.student_id,
                program_id=cmd.program_id,
            )

        # Determine threshold from skill configuration
        skill_meta = await self._skill_lookup.get_skill(cmd.skill_id)
        threshold_pct: float = 70.0
        coach_override_allowed: bool = False
        if skill_meta is not None:
            threshold_pct = getattr(skill_meta, "pass_threshold_pct", 70.0)
            coach_override_allowed = getattr(skill_meta, "coach_override_allowed", False)

        if cmd.coach_override and not coach_override_allowed:
            raise OverrideNotPermitted(
                "coach override is not enabled for this skill",
                skill_id=cmd.skill_id,
            )

        # Calculate pass
        score = (cmd.success_count / cmd.attempts_count) * 100.0
        passed = (
            calculate_skill_pass(cmd.attempts_count, cmd.success_count, threshold_pct)
            or cmd.coach_override
        )

        now = datetime.now(UTC)
        attempt = TestAttempt(
            attempt_id=str(new_ulid()),
            academy_id=_resolve_academy_id(),
            student_id=cmd.student_id,
            skill_id=cmd.skill_id,
            level_id=cmd.level_id,
            program_id=cmd.program_id,
            session_id=cmd.session_id,
            occurrence_id=cmd.occurrence_id,
            coach_id=cmd.coach_id,
            scoring_type=cmd.scoring_type,
            attempts_count=cmd.attempts_count,
            success_count=cmd.success_count,
            score=round(score, 2),
            passed=passed,
            coach_override=cmd.coach_override,
            override_reason=cmd.override_reason if cmd.coach_override else None,
            notes=cmd.notes,
            tested_at=now,
        )
        await self._test_attempts.save(attempt)

        # Update skill status
        existing_prog = await self._skill_progress.get(cmd.student_id, cmd.skill_id)
        new_status = "PASSED" if passed else "NEEDS_REVIEW"
        if existing_prog is None:
            updated_prog = StudentSkillProgress(
                skill_progress_id=str(new_ulid()),
                academy_id=_resolve_academy_id(),
                student_id=cmd.student_id,
                skill_id=cmd.skill_id,
                level_id=cmd.level_id,
                program_id=cmd.program_id,
                status=new_status,
                introduced_at=now,
                last_updated_at=now,
                last_updated_by=cmd.coach_id,
            )
        else:
            updated_prog = existing_prog.model_copy(
                update={
                    "status": new_status,
                    "last_updated_at": now,
                    "last_updated_by": cmd.coach_id,
                }
            )
        await self._skill_progress.upsert(updated_prog)

        # Check level completion if skill just passed
        level_completed = False
        if passed:
            all_skills = await self._skill_lookup.list_skills_for_level(cmd.level_id)
            required_ids = [
                s.skill_id
                for s in all_skills  # type: ignore[attr-defined]
                if getattr(s, "is_required", True)
            ]
            passed_records = await self._skill_progress.list_passed_for_student_level(
                cmd.student_id, cmd.level_id
            )
            passed_ids = {sp.skill_id for sp in passed_records}
            # Include the one we just passed
            passed_ids.add(cmd.skill_id)
            level_completed = check_level_completion(required_ids, passed_ids)

        if self._outbox is not None:
            academy_id = _resolve_academy_id()
            await self._outbox.append(
                SkillTestAttempted(
                    aggregate_id=attempt.attempt_id,
                    academy_id=academy_id,
                    payload=SkillTestAttemptedPayload(
                        student_id=cmd.student_id,
                        skill_id=cmd.skill_id,
                        level_id=cmd.level_id,
                        program_id=cmd.program_id,
                        coach_id=cmd.coach_id,
                        attempt_id=attempt.attempt_id,
                        attempts_count=cmd.attempts_count,
                        success_count=cmd.success_count,
                        score=round(score, 2),
                        passed=passed,
                    ),
                )
            )
            if passed:
                await self._outbox.append(
                    SkillPassed(
                        aggregate_id=attempt.attempt_id,
                        academy_id=academy_id,
                        payload=SkillPassedPayload(
                            student_id=cmd.student_id,
                            skill_id=cmd.skill_id,
                            level_id=cmd.level_id,
                            program_id=cmd.program_id,
                            coach_id=cmd.coach_id,
                            attempt_id=attempt.attempt_id,
                        ),
                    )
                )
            if level_completed:
                await self._outbox.append(
                    LevelCompleted(
                        aggregate_id=active.progress_id,
                        academy_id=academy_id,
                        payload=LevelCompletedPayload(
                            student_id=cmd.student_id,
                            level_id=cmd.level_id,
                            program_id=cmd.program_id,
                            progress_id=active.progress_id,
                        ),
                    )
                )

        return RecordTestAttemptResult(
            attempt_id=attempt.attempt_id,
            passed=passed,
            score=round(score, 2),
            skill_status=new_status,
            level_completed=level_completed,
        )
