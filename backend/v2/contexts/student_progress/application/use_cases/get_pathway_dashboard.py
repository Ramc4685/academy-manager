"""Use case: the owner's skill-pathway dashboard (who is moving, who is stuck).

Read-only roll-up over one program for the active roster:

* skills mastered this week and level-ups (certificates) this month;
* players per level, in pathway order;
* "almost there": exactly one required skill left on the current level;
* "stuck": no skill PASSED for ``STUCK_AFTER`` (counted from the later of the
  last pass and the day the student started the current level, so a student
  placed last week is not stuck yet);
* the level-up rule, read from each level's ``requires_admin_approval``.

Students with a level-up already pending are neither almost there nor stuck:
the next step is the owner's or the evening sweep's, not the student's.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, time, timedelta
from typing import Literal, Protocol
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from backend.v2.contexts.student_progress.application.ports import (
    CertificateRepository,
    LevelUpRecommendationRepository,
    StudentLevelProgressRepository,
    StudentSkillProgressRepository,
)
from backend.v2.contexts.student_progress.domain.models import SkillBoardStudentRef

STUCK_AFTER = timedelta(weeks=6)

LevelUpRule = Literal["automatic", "approve_first", "mixed"]


class PassedStatsRepository(Protocol):
    async def passed_stats_for_students(
        self, student_ids: list[str], program_id: str, *, since: datetime
    ) -> list[dict[str, object]]: ...


class PathwayLevelLookup(Protocol):
    async def list_levels_for_program(self, program_id: str) -> list[object]: ...
    async def list_skills_for_level(self, level_id: str) -> list[object]: ...


class SkillProgressReader(StudentSkillProgressRepository, PassedStatsRepository, Protocol):
    pass


class PathwayDashboardRequest(BaseModel):
    model_config = {"frozen": True}

    program_id: str
    students: list[SkillBoardStudentRef]
    now: datetime
    timezone: str


class DashboardLevel(BaseModel):
    level_id: str
    name: str
    sequence: int
    player_count: int
    requires_admin_approval: bool


class AlmostThereStudent(BaseModel):
    student_id: str
    student_name: str
    level_name: str
    level_sequence: int
    missing_skill_name: str


class StuckStudent(BaseModel):
    student_id: str
    student_name: str
    level_name: str
    level_sequence: int
    skills_passed: int
    skills_total: int
    last_win_at: datetime | None
    level_started_at: datetime


class PathwayDashboard(BaseModel):
    program_id: str
    skills_mastered_this_week: int
    level_ups_this_month: int
    levels: list[DashboardLevel]
    level_up_rule: LevelUpRule
    almost_there: list[AlmostThereStudent]
    stuck: list[StuckStudent]
    unplaced_count: int


class GetPathwayDashboard:
    def __init__(
        self,
        *,
        level_progress: StudentLevelProgressRepository,
        skill_progress: SkillProgressReader,
        recommendations: LevelUpRecommendationRepository,
        certificates: CertificateRepository,
        levels: PathwayLevelLookup,
    ) -> None:
        self._level_progress = level_progress
        self._skill_progress = skill_progress
        self._recs = recommendations
        self._certs = certificates
        self._levels = levels

    async def execute(self, req: PathwayDashboardRequest) -> PathwayDashboard:
        local_now = req.now.astimezone(ZoneInfo(req.timezone))
        week_start = datetime.combine(
            local_now.date() - timedelta(days=local_now.weekday()), time.min, local_now.tzinfo
        )
        month_start = datetime.combine(local_now.date().replace(day=1), time.min, local_now.tzinfo)
        stuck_before = req.now - STUCK_AFTER

        names = {s.student_id: s.student_name for s in req.students}
        student_ids = list(names)
        program_levels = sorted(
            await self._levels.list_levels_for_program(req.program_id),
            key=lambda lv: lv.sequence,  # type: ignore[attr-defined]
        )
        level_by_id = {lv.level_id: lv for lv in program_levels}  # type: ignore[attr-defined]

        # One row per student: legacy data can hold two active rows in a program.
        active = list(
            {
                row.student_id: row
                for row in reversed(
                    await self._level_progress.list_active_for_students(student_ids, req.program_id)
                )
                if row.level_id in level_by_id
            }.values()
        )
        pending = {
            rec.student_id
            for rec in await self._recs.list_active_for_students(student_ids, req.program_id)
        }
        passed_stats = {
            str(row["student_id"]): row
            for row in await self._skill_progress.passed_stats_for_students(
                student_ids, req.program_id, since=week_start
            )
        }
        level_ups = sum(
            1
            for cert in await self._certs.list_for_students(student_ids)
            if cert.program_id == req.program_id and _aware(cert.issued_at) >= month_start
        )

        rows_by_level: dict[str, list[str]] = {}
        for row in active:
            rows_by_level.setdefault(row.level_id, []).append(row.student_id)
        passed_by_student: dict[str, set[str]] = {}
        skills_by_level: dict[str, Sequence[object]] = {}
        for level_id, ids in rows_by_level.items():
            skills_by_level[level_id] = await self._levels.list_skills_for_level(level_id)
            for sp in await self._skill_progress.list_for_students(ids, level_id):
                if sp.status == "PASSED":
                    passed_by_student.setdefault(sp.student_id, set()).add(sp.skill_id)

        almost: list[AlmostThereStudent] = []
        stuck: list[StuckStudent] = []
        for row in active:
            if row.student_id in pending:
                continue
            level = level_by_id[row.level_id]
            skills = skills_by_level[row.level_id]
            passed = passed_by_student.get(row.student_id, set())
            required = [s for s in skills if getattr(s, "is_required", True)]
            missing = [s for s in required if s.skill_id not in passed]  # type: ignore[attr-defined]
            if not missing:
                continue  # level complete; the level-up is about to be queued
            if len(missing) == 1:
                almost.append(
                    AlmostThereStudent(
                        student_id=row.student_id,
                        student_name=names[row.student_id],
                        level_name=level.name,  # type: ignore[attr-defined]
                        level_sequence=level.sequence,  # type: ignore[attr-defined]
                        missing_skill_name=missing[0].name,  # type: ignore[attr-defined]
                    )
                )
            stats = passed_stats.get(row.student_id)
            last_win = _aware(stats["last_passed_at"]) if stats else None  # type: ignore[arg-type]
            started = _aware(row.started_at)
            if max(last_win or started, started) <= stuck_before:
                stuck.append(
                    StuckStudent(
                        student_id=row.student_id,
                        student_name=names[row.student_id],
                        level_name=level.name,  # type: ignore[attr-defined]
                        level_sequence=level.sequence,  # type: ignore[attr-defined]
                        skills_passed=len(required) - len(missing),
                        skills_total=len(required),
                        last_win_at=last_win,
                        level_started_at=started,
                    )
                )

        approvals = {bool(getattr(lv, "requires_admin_approval", False)) for lv in program_levels}
        rule: LevelUpRule = (
            "mixed" if len(approvals) > 1 else "approve_first" if True in approvals else "automatic"
        )
        return PathwayDashboard(
            program_id=req.program_id,
            skills_mastered_this_week=sum(
                int(row["passed_since"])  # type: ignore[call-overload]
                for row in passed_stats.values()
            ),
            level_ups_this_month=level_ups,
            levels=[
                DashboardLevel(
                    level_id=lv.level_id,  # type: ignore[attr-defined]
                    name=lv.name,  # type: ignore[attr-defined]
                    sequence=lv.sequence,  # type: ignore[attr-defined]
                    player_count=len(rows_by_level.get(lv.level_id, [])),  # type: ignore[attr-defined]
                    requires_admin_approval=bool(getattr(lv, "requires_admin_approval", False)),
                )
                for lv in program_levels
            ],
            level_up_rule=rule,
            almost_there=sorted(almost, key=lambda a: (a.level_sequence, a.student_name)),
            # Longest-stuck first: the oldest last win (never-won counts from placement).
            stuck=sorted(
                stuck, key=lambda s: (s.last_win_at or s.level_started_at, s.student_name)
            ),
            unplaced_count=len(student_ids) - len(active),
        )


def _aware(value: datetime) -> datetime:
    # Mongo hands back naive UTC datetimes unless the client is tz_aware.
    return value if value.tzinfo else value.replace(tzinfo=ZoneInfo("UTC"))
