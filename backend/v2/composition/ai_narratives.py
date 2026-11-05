"""B4 parent progress narrative wiring (plan 2026-11-04 Phase 2, Track B).

``_StudentNarrativeFacts`` reads the same state the evening wins provider
does (today's PASSED ``student_skill_progress`` rows, the level's skills and
criteria) and shapes it into ``ProgressNarrativeInput``: the only thing the
model sees. ``AcademyCoachReviewSwitch`` reads ``ai.coach_review_narratives``
the way ``AcademyAiCapLookup`` reads the cap. Attached at
``app.state.ai_narratives``; the coach routes in
``interfaces/coach/ai_narrative_routes.py`` read it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from backend.v2.composition.ai import AiComposition
from backend.v2.contexts.ai.application.use_cases.draft_progress_narrative import (
    DraftProgressNarrative,
    ProgressNarrativeInput,
    SkillMasteredToday,
)
from backend.v2.contexts.ai.application.use_cases.student_narratives import (
    DraftStudentNarrative,
    ReviewNarratives,
)
from backend.v2.contexts.ai.infrastructure.mongo_ai_call_repo import MongoAiCallRepository
from backend.v2.contexts.ai.infrastructure.mongo_ai_narrative_repo import (
    MongoAiNarrativeRepository,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_criterion_repo import (
    MongoCriterionRepository,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_level_repo import MongoLevelRepository
from backend.v2.contexts.curriculum.infrastructure.mongo_program_repo import (
    MongoProgramRepository,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_skill_repo import MongoSkillRepository
from backend.v2.contexts.enrollment.infrastructure.mongo_student_repo import (
    MongoStudentRepository,
)
from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import (
    MongoAcademyRepository,
)
from backend.v2.contexts.student_progress.infrastructure.mongo_skill_progress_repo import (
    MongoStudentSkillProgressRepository,
)
from backend.v2.shared.tenancy import current_academy_id


class AcademyCoachReviewSwitch:
    """``CoachReviewSwitch`` over the academy document: ``ai.coach_review_narratives``,
    default True (no UI yet; the owner sets it by hand)."""

    def __init__(self, academies: Any) -> None:
        self._academies = academies

    async def coach_review_required(self) -> bool:
        doc = await self._academies.find_by_id(current_academy_id())
        ai = (doc or {}).get("ai") if isinstance(doc, dict) else None
        value = ai.get("coach_review_narratives") if isinstance(ai, dict) else None
        return True if not isinstance(value, bool) else value


class _StudentNarrativeFacts:
    def __init__(
        self,
        *,
        skill_progress: Any,
        skills: Any,
        criteria: Any,
        levels: Any,
        programs: Any,
        students: Any,
    ) -> None:
        self._progress = skill_progress
        self._skills = skills
        self._criteria = criteria
        self._levels = levels
        self._programs = programs
        self._students = students

    async def facts_for(
        self, student_id: str, start: datetime, end: datetime
    ) -> ProgressNarrativeInput | None:
        rows = sorted(
            (
                r
                for r in await self._progress.list_passed_between(start, end)
                if r.student_id == student_id
            ),
            key=lambda r: r.skill_id,
        )
        if not rows:
            return None
        # shortcut: one level per note; a child passing skills in two levels on
        # one day gets the level of the first row. Revisit if coaches report it.
        level_id, program_id = rows[0].level_id, rows[0].program_id
        skills = {s.skill_id: s for s in await self._skills.list_for_level(level_id)}
        today = [r for r in rows if r.level_id == level_id and r.skill_id in skills]
        if not today:
            return None
        student = await self._students.get_by_id(student_id)
        level = await self._levels.get(level_id)
        program = await self._programs.get(program_id)
        required = {sid for sid, s in skills.items() if s.is_required}
        done = await self._progress.list_passed_for_student_level(student_id, level_id)
        passed = len({p.skill_id for p in done} & required)
        return ProgressNarrativeInput(
            child_first_name=((student.full_name if student else "").split() or ["Your child"])[0],
            level_name=level.name if level else "this level",
            program_name=program.name if program else "",
            skills_mastered_today=[
                SkillMasteredToday(
                    skill_name=skills[r.skill_id].name,
                    criteria=[
                        c.description for c in await self._criteria.list_for_skill(r.skill_id)
                    ],
                    coach_words=r.coach_note,
                )
                for r in today
            ],
            passed_in_level=passed,
            total_in_level=len(required),
            finished_level=bool(required) and passed >= len(required),
        )


@dataclass(frozen=True)
class AiNarrativesComposition:
    draft_for_student: DraftStudentNarrative
    review: ReviewNarratives


def compose_ai_narratives(db: Any, ai: AiComposition) -> AiNarrativesComposition:
    calls = MongoAiCallRepository(db)
    narratives = MongoAiNarrativeRepository(db)
    return AiNarrativesComposition(
        draft_for_student=DraftStudentNarrative(
            facts=_StudentNarrativeFacts(
                skill_progress=MongoStudentSkillProgressRepository(db),
                skills=MongoSkillRepository(db),
                criteria=MongoCriterionRepository(db),
                levels=MongoLevelRepository(db),
                programs=MongoProgramRepository(db),
                students=MongoStudentRepository(db),
            ),
            drafter=DraftProgressNarrative(
                llm=ai.llm, record_ai_call=ai.record_ai_call, entitlement=ai.entitlement
            ),
            review=AcademyCoachReviewSwitch(MongoAcademyRepository(db)),
            narratives=narratives,
            calls=calls,
        ),
        review=ReviewNarratives(narratives=narratives, calls=calls),
    )
