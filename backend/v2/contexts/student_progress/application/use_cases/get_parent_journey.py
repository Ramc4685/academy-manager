"""Use case: the parent "how far along" view for one child in one program.

One read model for the page parents land on from the evening win email:
where the child sits on the level ladder, required and optional skills
passed in every level, a pace estimate when recent passes support one, the level's
skill checklist, recent wins and the skill to practise at home.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel

from backend.v2.contexts.student_progress.application.level_skill_counts import (
    LevelSkillCounts,
    count_level_skills,
)
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
from backend.v2.contexts.student_progress.domain.models import SkillStatus, StudentSkillProgress

JourneyLevelState = Literal["done", "current", "upcoming"]
JourneySkillState = Literal["got_it", "working_on_it", "coming_up"]

RECENT_PASS_LOOKBACK = 20
RECENT_WINS_LIMIT = 6


class JourneyLevel(LevelSkillCounts):
    level_id: str
    name: str
    number: int
    state: JourneyLevelState
    color: str | None = None


class JourneySkill(BaseModel):
    model_config = {"frozen": True}
    skill_id: str
    name: str
    state: JourneySkillState


class JourneyCurrentLevel(LevelSkillCounts):
    level_id: str
    name: str
    number: int
    skills_done: int
    skills_total: int
    #: Required skills still to pass before the level is complete.
    skills_remaining: int
    has_next_level: bool
    pace_weeks: int | None
    color: str | None = None


class JourneyWin(BaseModel):
    model_config = {"frozen": True}
    kind: Literal["skill", "certificate"]
    at: datetime
    title: str
    cert_id: str | None = None
    cert_number: str | None = None
    #: The coach's optional note to the parent on this win.
    coach_note: str | None = None


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
    #: The latest completed placement was the program's last level.
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
        active = await self._level_progress.get_active(student_id, program_id)
        program_levels = sorted(
            await self._skill_lookup.list_levels_for_program(program_id),
            key=lambda lvl: getattr(lvl, "sequence", 0),
        )
        level_ids = [str(getattr(lvl, "level_id", "")) for lvl in program_levels]
        current_index = (
            level_ids.index(active.level_id) if active and active.level_id in level_ids else None
        )
        catalog, progress = await asyncio.gather(
            self._skill_lookup.list_skills_for_program(program_id),
            self._skill_progress.list_for_student_program(student_id, program_id),
        )
        skills_by_level: dict[str, list[object]] = defaultdict(list)
        for skill in catalog:
            skills_by_level[str(getattr(skill, "level_id", ""))].append(skill)
        statuses = {row.skill_id: row.status for row in progress}
        counts = {
            level_id: count_level_skills(skills, statuses)
            for level_id, skills in skills_by_level.items()
        }

        recent_pass_rows = sorted(
            (row for row in progress if row.status == "PASSED" and not row.silent),
            key=lambda row: _as_utc(row.last_updated_at),
            reverse=True,
        )
        recent_wins = await self._recent_wins(student_id, program_id, recent_pass_rows)
        completed_rows = [
            row
            for row in await self._level_progress.list_for_student(student_id)
            if row.program_id == program_id and row.status == "completed" and row.completed_at
        ]
        completed = {row.level_id for row in completed_rows}
        last_completed = max(
            completed_rows, key=lambda r: _as_utc(r.completed_at or r.started_at), default=None
        )
        complete = bool(
            active is None
            and level_ids
            and last_completed
            and last_completed.level_id == level_ids[-1]
        )

        def position(index: int) -> JourneyLevelState:
            if index == current_index:
                return "current"
            level_id = level_ids[index]
            if level_id in completed or (level_id in counts and counts[level_id].required_complete):
                return "done"
            return "upcoming"

        empty_counts = count_level_skills([], {})
        levels = [
            JourneyLevel(
                level_id=level_ids[i],
                name=str(getattr(lvl, "name", "")),
                number=i + 1,
                color=getattr(lvl, "display_color", None),
                state=position(i),
                **counts.get(level_ids[i], empty_counts).model_dump(),
            )
            for i, lvl in enumerate(program_levels)
        ]
        if active is None:
            # Graduates and unplaced learners both lack an active placement.
            return ParentJourney(
                student_id=student_id,
                program_id=program_id,
                levels=levels,
                current_level=None,
                skills=[],
                recent_wins=recent_wins,
                focus_skill_id=None,
                focus_skill_name=None,
                pathway_complete=complete,
            )

        skills = sorted(skills_by_level[active.level_id], key=lambda s: getattr(s, "sequence", 0))

        def status_of(skill: object) -> SkillStatus:
            return statuses.get(str(getattr(skill, "skill_id", "")), "NOT_STARTED")

        current_counts = counts.get(active.level_id, empty_counts)
        remaining = current_counts.required_total - current_counts.required_passed
        required_ids = {
            str(getattr(skill, "skill_id", ""))
            for skill in skills
            if getattr(skill, "is_required", True)
        }
        recent_passes = [
            _as_utc(row.last_updated_at) for row in recent_pass_rows if row.skill_id in required_ids
        ][:RECENT_PASS_LOOKBACK]
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
                color=getattr(level_meta, "display_color", None),
                **current_counts.model_dump(),
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

    async def _recent_wins(
        self, student_id: str, program_id: str, passed: list[StudentSkillProgress]
    ) -> list[JourneyWin]:
        wins: list[JourneyWin] = []
        for row in passed[:RECENT_WINS_LIMIT]:
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
                    coach_note=row.coach_note,
                )
            )
        for cert in await self._certs.list_for_student(student_id):
            if cert.program_id != program_id:
                continue
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
