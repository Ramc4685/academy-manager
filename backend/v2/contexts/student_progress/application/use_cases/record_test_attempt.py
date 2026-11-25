"""Use case: coach records a test attempt for a student skill.

This is the one writer of a tested PASSED, so it owns the skill's pass rule
for every route (detailed test, tap-to-master): LEAD_COACH refuses a pass
from an assistant-only coach, and N_TRIES counts a passing attempt as one
try, passing the skill only on the Nth.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field, model_validator

from backend.v2.contexts.student_progress.application.ports import (
    SkillLookup,
    StudentLevelProgressRepository,
    StudentSkillProgressRepository,
    TestAttemptRepository,
)
from backend.v2.contexts.student_progress.domain.errors import (
    OverrideNotPermitted,
    PassNeedsLeadCoach,
    SkillNotOnCurrentLevel,
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
from backend.v2.shared.idempotency import IdempotencyStore, idempotent
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy import current_academy_id


def _resolve_academy_id() -> str:
    return current_academy_id()


class RecordTestAttemptCommand(BaseModel):
    model_config = {"frozen": True}
    student_id: str
    skill_id: str
    program_id: str
    coach_id: str
    #: False for an assistant-only coach. Required, so no route can forget
    #: it: a LEAD_COACH skill refuses a pass when it is False.
    #: It also guards taking a lead-coach pass away with a failing attempt.
    can_sign_off: bool
    session_id: str | None = None
    occurrence_id: str | None = None
    scoring_type: str = "ATTEMPT_BASED"
    attempts_count: int = Field(ge=1)
    success_count: int = Field(ge=0)
    coach_override: bool = False
    override_reason: str | None = None
    notes: str = ""
    # Client-generated ULID used as the idempotency key so offline-sync or
    # network retries return the original result instead of inserting
    # duplicate attempts and re-emitting progress events.
    mutation_id: str | None = None
    #: Set only by the trusted class entry point: the skill may sit on another
    #: active level of the same program. Its pass counts toward its own level
    #: and never completes (so never queues or certifies) the active level.
    off_level_ok: bool = False
    #: When the skill was demonstrated (the dated class); entry time otherwise.
    observed_at: datetime | None = None

    @model_validator(mode="after")
    def _success_not_above_attempts(self) -> RecordTestAttemptCommand:
        if self.success_count > self.attempts_count:
            raise ValueError("success_count cannot exceed attempts_count")
        return self


class RecordTestAttemptResult(BaseModel):
    model_config = {"frozen": True}
    attempt_id: str
    passed: bool
    score: float
    skill_status: str
    level_completed: bool
    #: Tries counted so far on an N_TRIES skill (0 for the other rules).
    tries: int = 0


class RecordTestAttempt:
    def __init__(
        self,
        *,
        level_progress: StudentLevelProgressRepository,
        skill_progress: StudentSkillProgressRepository,
        test_attempts: TestAttemptRepository,
        skill_lookup: SkillLookup,
        outbox: Outbox | None = None,
        idempotency_store: IdempotencyStore | None = None,
    ) -> None:
        self._level_progress = level_progress
        self._skill_progress = skill_progress
        self._test_attempts = test_attempts
        self._skill_lookup = skill_lookup
        self._outbox = outbox
        self._idempotency_store = idempotency_store

    async def execute(self, cmd: RecordTestAttemptCommand) -> RecordTestAttemptResult:
        if self._idempotency_store is not None and cmd.mutation_id:
            legacy = await self._replay_legacy_key(cmd)
            if legacy is not None:
                return legacy
            return await self._execute_idempotent(cmd)
        return await self._execute(cmd)

    async def _replay_legacy_key(
        self, cmd: RecordTestAttemptCommand
    ) -> RecordTestAttemptResult | None:
        """A result stored under the old unscoped key, if it is provably this coach's.

        An offline mark recorded before the key gained the academy and coach and
        retried after must replay, not record a second attempt (an N_TRIES skill
        would count an extra try). The key alone is client-sent, so the stored
        attempt must exist in this tenant for this student, skill and coach.
        """
        # shortcut: reads the pre-scoping key; delete 7 days after deploy, once the idempotency TTL has expired them all.
        assert self._idempotency_store is not None
        stored = await self._idempotency_store.get(f"record_test_attempt:{cmd.mutation_id}")
        try:
            result = RecordTestAttemptResult.model_validate(stored["value"]["data"])  # type: ignore[index]
        except (KeyError, TypeError, ValueError):
            return None
        attempts = await self._test_attempts.list_for_student_skill(cmd.student_id, cmd.skill_id)
        owned = any(
            a.attempt_id == result.attempt_id and a.coach_id == cmd.coach_id for a in attempts
        )
        return result if owned else None

    @idempotent(
        # mutation_id is client-sent, so the key carries the tenant and the
        # (server-derived) coach: two coaches or academies never share a result.
        key_from=lambda self, cmd: (
            f"record_test_attempt:{_resolve_academy_id()}:{cmd.coach_id}:{cmd.mutation_id}"
        ),
        result_type=RecordTestAttemptResult,
    )
    async def _execute_idempotent(self, cmd: RecordTestAttemptCommand) -> RecordTestAttemptResult:
        return await self._execute(cmd)

    async def _execute(self, cmd: RecordTestAttemptCommand) -> RecordTestAttemptResult:
        active = await self._level_progress.get_active(cmd.student_id, cmd.program_id)
        if active is None:
            raise StudentNotPlaced(
                "student has no active level",
                student_id=cmd.student_id,
                program_id=cmd.program_id,
            )

        skill_meta = await self._skill_lookup.get_skill(cmd.skill_id)
        # Only the active level's skills count: a client-sent level_id used to
        # land attempts (and passes) on a level the student is not in. The
        # class entry point may also record another active level's skill.
        on_level = getattr(skill_meta, "level_id", None) == active.level_id
        if not on_level and not (
            cmd.off_level_ok and await self._in_active_curriculum(skill_meta, cmd.program_id)
        ):
            raise SkillNotOnCurrentLevel(
                "skill is not on the student's current level",
                student_id=cmd.student_id,
                skill_id=cmd.skill_id,
            )
        level_id: str = skill_meta.level_id  # type: ignore[union-attr]
        threshold_pct: float = getattr(skill_meta, "pass_threshold_pct", 70.0)
        coach_override_allowed: bool = getattr(skill_meta, "coach_override_allowed", False)

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
        pass_rule = getattr(skill_meta, "pass_rule", "ONE_TAP")
        existing_prog = await self._skill_progress.get(cmd.student_id, cmd.skill_id)
        already_passed = existing_prog is not None and existing_prog.status == "PASSED"
        # A lead-coach skill is signed off, and taken back, by a lead coach only.
        if pass_rule == "LEAD_COACH" and not cmd.can_sign_off and (passed or already_passed):
            raise PassNeedsLeadCoach(
                "a lead coach signs this skill off",
                student_id=cmd.student_id,
                skill_id=cmd.skill_id,
            )

        now = datetime.now(UTC)
        attempt = TestAttempt(
            attempt_id=str(new_ulid()),
            academy_id=_resolve_academy_id(),
            student_id=cmd.student_id,
            skill_id=cmd.skill_id,
            level_id=level_id,
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
            observed_at=cmd.observed_at or now,
            # The observer is coach_id; a pass also names who signed it off.
            signed_off_by=cmd.coach_id if passed and cmd.can_sign_off else None,
        )
        await self._test_attempts.save(attempt)

        # Update skill status
        tries = 0
        written = False
        if passed and pass_rule == "N_TRIES" and already_passed:
            # A pass stays a pass: a credit (0 tries) or a pass from before the
            # skill moved to N_TRIES is not demoted by a later passing test.
            tries = existing_prog.tries if existing_prog is not None else 0
            new_status = "PASSED"
        elif passed and pass_rule == "N_TRIES":
            # A passing attempt is one try; the skill passes on the Nth.
            needed: int = skill_meta.pass_tries  # type: ignore[union-attr]
            if existing_prog is None:
                await self._skill_progress.insert_if_missing(
                    StudentSkillProgress(
                        skill_progress_id=str(new_ulid()),
                        academy_id=_resolve_academy_id(),
                        student_id=cmd.student_id,
                        skill_id=cmd.skill_id,
                        level_id=level_id,
                        program_id=cmd.program_id,
                        status="NOT_STARTED",
                        introduced_at=now,
                        last_updated_at=now,
                        last_updated_by=cmd.coach_id,
                    )
                )
                existing_prog = await self._skill_progress.get(cmd.student_id, cmd.skill_id)
            tries = await self._skill_progress.increment_tries(cmd.student_id, cmd.skill_id, 1) or 0
            passed = tries >= needed
            new_status = "PASSED" if passed else "PRACTICING"
            if not passed:
                # Conditional: a concurrent tap may have passed it meanwhile.
                await self._skill_progress.set_status_unless_passed(
                    cmd.student_id, cmd.skill_id, "PRACTICING", at=now, by=cmd.coach_id
                )
                current = await self._skill_progress.get(cmd.student_id, cmd.skill_id)
                new_status = current.status if current is not None else new_status
                written = True
        else:
            new_status = "PASSED" if passed else "NEEDS_REVIEW"
        if not written:
            if existing_prog is None:
                updated_prog = StudentSkillProgress(
                    skill_progress_id=str(new_ulid()),
                    academy_id=_resolve_academy_id(),
                    student_id=cmd.student_id,
                    skill_id=cmd.skill_id,
                    level_id=level_id,
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
                        # A real pass is always announced, even over a silent credit.
                        "silent": False,
                    }
                )
            await self._skill_progress.upsert(updated_prog)

        # Check level completion if skill just passed
        level_completed = False
        if passed and on_level:
            all_skills = await self._skill_lookup.list_skills_for_level(level_id)
            required_ids = [s.skill_id for s in all_skills if getattr(s, "is_required", True)]
            passed_records = await self._skill_progress.list_passed_for_student_level(
                cmd.student_id, level_id
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
                        level_id=level_id,
                        program_id=cmd.program_id,
                        coach_id=cmd.coach_id,
                        attempt_id=attempt.attempt_id,
                        attempts_count=cmd.attempts_count,
                        success_count=cmd.success_count,
                        score=round(score, 2),
                        passed=attempt.passed,
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
                            level_id=level_id,
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
                            level_id=level_id,
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
            tries=tries,
        )

    async def _in_active_curriculum(self, skill_meta: object, program_id: str) -> bool:
        """The skill and its level are live curriculum of this program."""
        if skill_meta is None or getattr(skill_meta, "program_id", None) != program_id:
            return False
        if not getattr(skill_meta, "is_active", True):
            return False
        level = await self._skill_lookup.get_level(skill_meta.level_id)  # type: ignore[attr-defined]
        return level is not None and bool(getattr(level, "is_active", True))
