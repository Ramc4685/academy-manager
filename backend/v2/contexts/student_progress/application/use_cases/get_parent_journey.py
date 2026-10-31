"""Use case: the parent "how far along" view for one child in one program.

One read model for the page parents land on from the evening win email:
where the child sits on the level ladder, how much of the current level is
done, a pace estimate (only when recent passes support one), the level's
skill checklist, recent wins and the skill to practise at home.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel

from backend.v2.contexts.student_progress.application.ports import (
    CertificateRepository,
    SkillLookup,
    StudentLevelProgressRepository,
    StudentSkillProgressRepository,
    TestAttemptRepository,
)
from backend.v2.contexts.student_progress.application.use_cases.get_teaching_focus import (
    _pick_next_skill,
)
from backend.v2.contexts.student_progress.domain.logic import estimate_weeks_to_next_level
from backend.v2.contexts.student_progress.domain.models import SkillStatus

JourneyLevelState = Literal["done", "current", "upcoming"]
JourneySkillState = Literal["got_it", "working_on_it", "coming_up"]

RECENT_PASS_LOOKBACK = 20
RECENT_WINS_LIMIT = 6


class JourneyLevel(BaseModel):
    model_config = {"frozen": True}
    level_id: str
    name: str
    number: int
    state: JourneyLevelState


class JourneySkill(BaseModel):
    model_config = {"frozen": True}
    skill_id: str
    name: str
    state: JourneySkillState


class JourneyCurrentLevel(BaseModel):
    model_config = {"frozen": True}
    level_id: str
    name: str
    number: int
    skills_done: int
    skills_total: int
    #: Required skills still to pass before the level is complete.
    skills_remaining: int
    has_next_level: bool
    pace_weeks: int | None


class JourneyWin(BaseModel):
    model_config = {"frozen": True}
    kind: Literal["skill", "certificate"]
    at: datetime
    title: str
    cert_id: str | None = None
    cert_number: str | None = None


class ParentJourney(BaseModel):
    model_config = {"frozen": True}
    student_id: str
    program_id: str
    levels: list[JourneyLevel]
    current_level: JourneyCurrentLevel | None
    skills: list[JourneySkill]
    recent_wins: list[JourneyWin]
    #: The skill the coach works on next; the BFF looks up its drill video.
    focus_skill_id: str | None
    focus_skill_name: str | None
    #: Finished the program's last level: no active row, every level done.
    pathway_complete: bool = False


def _skill_state(status: SkillStatus) -> JourneySkillState:
    if status == "PASSED":
        return "got_it"
    if status == "NOT_STARTED":
        return "coming_up"
    return "working_on_it"


def _as_utc(value: datetime) -> datetime:
    # Mongo hands back naive datetimes; every stored time is UTC.
    return value if value.tzinfo else value.replace(tzinfo=UTC)


class GetParentJourney:
    def __init__(
        self,
        *,
        level_progress: StudentLevelProgressRepository,
        skill_progress: StudentSkillProgressRepository,
        skill_lookup: SkillLookup,
        certificates: CertificateRepository,
        test_attempts: TestAttemptRepository,
    ) -> None:
        self._level_progress = level_progress
        self._skill_progress = skill_progress
        self._skill_lookup = skill_lookup
        self._certs = certificates
        self._test_attempts = test_attempts

    async def execute(
        self, student_id: str, program_id: str, *, now: datetime | None = None
    ) -> ParentJourney:
        now = now or datetime.now(UTC)
        recent_wins = await self._recent_wins(student_id)
        active = await self._level_progress.get_active(student_id, program_id)
        program_levels = sorted(
            await self._skill_lookup.list_levels_for_program(program_id),
            key=lambda lvl: getattr(lvl, "sequence", 0),
        )
        if active is None:
            # Approving the last level completes the active row without
            # opening another, so "no active row" also means "finished".
            complete = await self._finished_pathway(student_id, program_id, program_levels)
            return ParentJourney(
                student_id=student_id,
                program_id=program_id,
                levels=[
                    JourneyLevel(
                        level_id=str(getattr(lvl, "level_id", "")),
                        name=str(getattr(lvl, "name", "")),
                        number=i + 1,
                        state="done",
                    )
                    for i, lvl in enumerate(program_levels)
                ]
                if complete
                else [],
                current_level=None,
                skills=[],
                recent_wins=recent_wins,
                focus_skill_id=None,
                focus_skill_name=None,
                pathway_complete=complete,
            )

        current_index = next(
            (
                i
                for i, lvl in enumerate(program_levels)
                if getattr(lvl, "level_id", None) == active.level_id
            ),
            None,
        )
        levels = [
            JourneyLevel(
                level_id=str(getattr(lvl, "level_id", "")),
                name=str(getattr(lvl, "name", "")),
                number=i + 1,
                state=(
                    "current"
                    if i == current_index
                    else "done"
                    if current_index is not None and i < current_index
                    else "upcoming"
                ),
            )
            for i, lvl in enumerate(program_levels)
        ]

        skills = sorted(
            await self._skill_lookup.list_skills_for_level(active.level_id),
            key=lambda s: getattr(s, "sequence", 0),
        )
        rows = await self._skill_progress.list_for_student_level(student_id, active.level_id)
        status_by_skill: dict[str, SkillStatus] = {r.skill_id: r.status for r in rows}

        def status_of(skill: object) -> SkillStatus:
            return status_by_skill.get(str(getattr(skill, "skill_id", "")), "NOT_STARTED")

        remaining = sum(
            1 for s in skills if getattr(s, "is_required", True) and status_of(s) != "PASSED"
        )
        recent_passes = [
            _as_utc(r.last_updated_at)
            for r in await self._skill_progress.list_recent_for_student(
                student_id, limit=RECENT_PASS_LOOKBACK
            )
            if r.status == "PASSED"
        ]
        level_meta = (
            program_levels[current_index]
            if current_index is not None
            else await self._skill_lookup.get_level(active.level_id)
        )
        focus = _pick_next_skill(skills, status_of)

        return ParentJourney(
            student_id=student_id,
            program_id=program_id,
            levels=levels,
            current_level=JourneyCurrentLevel(
                level_id=active.level_id,
                name=str(getattr(level_meta, "name", "")),
                number=(current_index + 1) if current_index is not None else 1,
                skills_done=sum(1 for s in skills if status_of(s) == "PASSED"),
                skills_total=len(skills),
                skills_remaining=remaining,
                has_next_level=current_index is not None
                and current_index < len(program_levels) - 1,
                pace_weeks=estimate_weeks_to_next_level(recent_passes, remaining, now),
            ),
            skills=[
                JourneySkill(
                    skill_id=str(getattr(s, "skill_id", "")),
                    name=str(getattr(s, "name", "")),
                    state=_skill_state(status_of(s)),
                )
                for s in skills
            ],
            recent_wins=recent_wins,
            focus_skill_id=str(getattr(focus, "skill_id", "")) if focus else None,
            focus_skill_name=str(getattr(focus, "name", "")) if focus else None,
        )

    async def _finished_pathway(
        self, student_id: str, program_id: str, program_levels: list[object]
    ) -> bool:
        if not program_levels:
            return False
        completed = [
            r
            for r in await self._level_progress.list_for_student(student_id)
            if r.program_id == program_id and r.status == "completed" and r.completed_at
        ]
        if not completed:
            return False
        latest = max(completed, key=lambda r: _as_utc(r.completed_at or r.started_at))
        return bool(latest.level_id == getattr(program_levels[-1], "level_id", None))

    async def _recent_wins(self, student_id: str) -> list[JourneyWin]:
        rows = await self._skill_progress.list_recent_for_student(
            student_id, limit=RECENT_PASS_LOOKBACK
        )
        wins: list[JourneyWin] = []
        for row in [r for r in rows if r.status == "PASSED"][:RECENT_WINS_LIMIT]:
            skill = await self._skill_lookup.get_skill(row.skill_id)
            # Only the pass date comes from the attempt: its notes are
            # coach-facing, with no parent visibility flag (unlike ProgressNote).
            attempts = await self._test_attempts.list_for_student_skill(student_id, row.skill_id)
            passing = max(
                (a for a in attempts if a.passed), key=lambda a: a.tested_at, default=None
            )
            wins.append(
                JourneyWin(
                    kind="skill",
                    at=_as_utc(passing.tested_at if passing else row.last_updated_at),
                    title=str(getattr(skill, "name", "")) or "A new skill",
                )
            )
        for cert in await self._certs.list_for_student(student_id):
            wins.append(
                JourneyWin(
                    kind="certificate",
                    at=_as_utc(cert.completed_at),
                    title=cert.level_name,
                    cert_id=cert.cert_id,
                    cert_number=cert.cert_number,
                )
            )
        wins.sort(key=lambda w: w.at, reverse=True)
        return wins[:RECENT_WINS_LIMIT]
