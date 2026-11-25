"""Use case: coach taps the students who mastered a skill in class.

One tap records a 1-of-1 test attempt (so the pass keeps the same audit
trail, events and level-completion check as the detailed test flow) and,
when it was the last required skill of the level, queues the level-up as a
recommendation. ``AutoApproveLevelUps`` lands it that evening; until then
``UnmarkSkillMastered`` takes it back.

The skill's pass rule decides what a tap means: ONE_TAP passes, N_TRIES
counts taps (any days) and passes on the Nth, LEAD_COACH passes only when
the caller can sign off (not assistant-only).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from backend.v2.contexts.student_progress.application.ports import (
    SkillLookup,
    StudentLevelProgressRepository,
    StudentSkillProgressRepository,
)
from backend.v2.contexts.student_progress.application.use_cases.recommend_level_up import (
    RecommendLevelUp,
    RecommendLevelUpCommand,
)
from backend.v2.contexts.student_progress.application.use_cases.record_test_attempt import (
    RecordTestAttempt,
    RecordTestAttemptCommand,
)
from backend.v2.contexts.student_progress.domain.errors import (
    ActiveRecommendationExists,
    EnrollmentEnded,
    PassNeedsLeadCoach,
    SkillNotOnCurrentLevel,
)
from backend.v2.contexts.student_progress.domain.logic import check_level_completion

MASTERED_NOTE = "Marked as mastered in class"

MasteredOutcomeKind = Literal[
    "mastered",
    "already_mastered",
    "not_on_level",
    "not_placed",
    "try_recorded",  # N_TRIES: counted, not yet N
    "needs_lead",  # LEAD_COACH: an assistant tapped; nothing written
]


class MarkSkillMasteredCommand(BaseModel):
    model_config = {"frozen": True}
    skill_id: str
    program_id: str
    student_ids: list[str]
    coach_id: str
    session_id: str | None = None
    #: False for an assistant-only coach: LEAD_COACH skills then need a lead.
    can_sign_off: bool
    #: Trusted class entry point only (see ``RecordTestAttemptCommand``): a
    #: skill of another active level counts there and never queues a level-up.
    off_level_ok: bool = False
    occurrence_id: str | None = None
    observed_at: datetime | None = None
    #: Per-student retries replay instead of counting another N_TRIES try.
    mutation_id: str | None = None


class MasteredOutcome(BaseModel):
    model_config = {"frozen": True}
    student_id: str
    outcome: MasteredOutcomeKind
    level_up_queued: bool = False
    #: Taps counted so far on an N_TRIES skill.
    tries: int = 0
    #: The skill sits on another level than the student's active one.
    off_level: bool = False


class MarkSkillMastered:
    def __init__(
        self,
        *,
        level_progress: StudentLevelProgressRepository,
        skill_progress: StudentSkillProgressRepository,
        skill_lookup: SkillLookup,
        record_test_attempt: RecordTestAttempt,
        recommend_level_up: RecommendLevelUp,
    ) -> None:
        self._level_progress = level_progress
        self._skill_progress = skill_progress
        self._skill_lookup = skill_lookup
        self._record = record_test_attempt
        self._recommend = recommend_level_up

    async def execute(self, cmd: MarkSkillMasteredCommand) -> list[MasteredOutcome]:
        skill = await self._skill_lookup.get_skill(cmd.skill_id)
        outcomes: list[MasteredOutcome] = []
        for student_id in dict.fromkeys(cmd.student_ids):
            outcomes.append(await self._mark_one(cmd, student_id, skill))
        return outcomes

    async def _mark_one(
        self, cmd: MarkSkillMasteredCommand, student_id: str, skill: Any
    ) -> MasteredOutcome:
        skill_level_id = getattr(skill, "level_id", None)
        active = await self._level_progress.get_active(student_id, cmd.program_id)
        if active is None:
            return MasteredOutcome(student_id=student_id, outcome="not_placed")
        # Only the active level's skills count toward moving up; a skill from
        # another level never completes anything.
        on_level = skill_level_id == active.level_id
        if not on_level and not cmd.off_level_ok:
            return MasteredOutcome(student_id=student_id, outcome="not_on_level")
        existing = await self._skill_progress.get(student_id, cmd.skill_id)
        if existing is not None and existing.status == "PASSED" and not on_level:
            return MasteredOutcome(
                student_id=student_id, outcome="already_mastered", off_level=True
            )
        if existing is not None and existing.status == "PASSED":
            # Skills passed before tap-to-master (or a level-up the owner
            # rejected) leave a complete level with nothing queued; a re-tap
            # is the coach's way to move them on.
            complete = await self._level_complete(student_id, active.level_id)
            return MasteredOutcome(
                student_id=student_id,
                outcome="already_mastered",
                level_up_queued=complete and await self._queue_level_up(cmd, student_id),
            )

        # RecordTestAttempt applies the pass rule (one predicate for every route).
        try:
            result = await self._record.execute(
                RecordTestAttemptCommand(
                    student_id=student_id,
                    skill_id=cmd.skill_id,
                    program_id=cmd.program_id,
                    coach_id=cmd.coach_id,
                    can_sign_off=cmd.can_sign_off,
                    session_id=cmd.session_id,
                    occurrence_id=cmd.occurrence_id,
                    scoring_type="COACH_APPROVAL",
                    attempts_count=1,
                    success_count=1,
                    notes=MASTERED_NOTE,
                    off_level_ok=cmd.off_level_ok,
                    observed_at=cmd.observed_at,
                    mutation_id=f"{cmd.mutation_id}:{student_id}" if cmd.mutation_id else None,
                )
            )
        except PassNeedsLeadCoach:
            return MasteredOutcome(
                student_id=student_id, outcome="needs_lead", off_level=not on_level
            )
        except SkillNotOnCurrentLevel:
            # Off-level and not live curriculum of this program (retired skill or level).
            return MasteredOutcome(student_id=student_id, outcome="not_on_level", off_level=True)
        if not result.passed:
            return MasteredOutcome(
                student_id=student_id,
                outcome="try_recorded",
                tries=result.tries,
                off_level=not on_level,
            )
        queued = on_level and result.level_completed and await self._queue_level_up(cmd, student_id)
        return MasteredOutcome(
            student_id=student_id,
            outcome="mastered",
            level_up_queued=queued,
            tries=result.tries,
            off_level=not on_level,
        )

    async def _level_complete(self, student_id: str, level_id: str) -> bool:
        skills = await self._skill_lookup.list_skills_for_level(level_id)
        required = [s.skill_id for s in skills if getattr(s, "is_required", True)]  # type: ignore[attr-defined]
        passed = await self._skill_progress.list_passed_for_student_level(student_id, level_id)
        return check_level_completion(required, {p.skill_id for p in passed})

    async def _queue_level_up(self, cmd: MarkSkillMasteredCommand, student_id: str) -> bool:
        try:
            await self._recommend.execute(
                RecommendLevelUpCommand(
                    student_id=student_id, program_id=cmd.program_id, recommended_by=cmd.coach_id
                )
            )
        except ActiveRecommendationExists:
            return True
        except EnrollmentEnded:
            # Roster-visible but not live (e.g. held): the pass stands, the
            # move waits, and the rest of the class still gets marked.
            return False
        return True
