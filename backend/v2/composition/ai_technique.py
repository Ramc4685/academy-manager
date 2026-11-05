"""B6 part 2 wiring: the coach's text-only technique observation draft.

``StudentProgressTechniqueCandidates`` reads the student's first name and the
criteria of their CURRENT level through the existing enrollment, curriculum
and student_progress repositories. Attached at ``app.state.ai_technique``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.v2.composition.ai import AiComposition
from backend.v2.contexts.ai.application.use_cases.draft_technique_observation import (
    DraftTechniqueObservation,
    DraftTechniqueObservationForStudent,
    TechniqueCandidate,
    TechniqueFacts,
)
from backend.v2.contexts.ai.infrastructure.disabled_llm_port import DisabledLlmPort
from backend.v2.contexts.curriculum.application.use_cases.manage_program import (
    ResolveDefaultActiveProgram,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_criterion_repo import (
    MongoCriterionRepository,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_level_repo import MongoLevelRepository
from backend.v2.contexts.curriculum.infrastructure.mongo_program_repo import MongoProgramRepository
from backend.v2.contexts.curriculum.infrastructure.mongo_skill_repo import MongoSkillRepository
from backend.v2.contexts.enrollment.infrastructure.mongo_student_repo import (
    MongoStudentRepository,
)
from backend.v2.contexts.student_progress.infrastructure.curriculum_lookup_adapter import (
    CurriculumSkillLookupAdapter,
)
from backend.v2.contexts.student_progress.infrastructure.mongo_level_progress_repo import (
    MongoStudentLevelProgressRepository,
)


class StudentProgressTechniqueCandidates:
    """``TechniqueCandidateSource``: first name only (never the surname), and
    every criterion of the skills on the student's active level in the
    academy's default program."""

    def __init__(
        self,
        *,
        students: Any,
        resolve_default_program: Any,
        level_progress: Any,
        skill_lookup: Any,
        criteria: Any,
    ) -> None:
        self._students = students
        self._resolve_default_program = resolve_default_program
        self._level_progress = level_progress
        self._skill_lookup = skill_lookup
        self._criteria = criteria

    async def candidates(self, student_id: str) -> TechniqueFacts:
        students = await self._students.by_ids([student_id])
        full_name = str(getattr(students[0], "full_name", "") if students else "")
        first_name = full_name.split()[0] if full_name.split() else "Your child"
        program = await self._resolve_default_program.execute()
        active = await self._level_progress.get_active(student_id, str(program.program_id))
        rows: list[TechniqueCandidate] = []
        if active is not None:
            for skill in await self._skill_lookup.list_skills_for_level(active.level_id):
                for crit in await self._criteria.list_for_skill(str(skill.skill_id)):
                    description = str(getattr(crit, "description", "") or "")
                    if description:
                        rows.append(
                            TechniqueCandidate(
                                criterion_id=str(crit.criterion_id),
                                skill_id=str(skill.skill_id),
                                skill_name=str(getattr(skill, "name", "") or skill.skill_id),
                                description=description,
                            )
                        )
        return TechniqueFacts(child_first_name=first_name, candidates=rows[:40])


@dataclass(frozen=True)
class AiTechniqueComposition:
    draft_for_student: DraftTechniqueObservationForStudent
    #: A model is wired for this deployment; the coach shell hides the draft box otherwise.
    enabled: bool


def compose_ai_technique(db: Any, ai: AiComposition) -> AiTechniqueComposition:
    source = StudentProgressTechniqueCandidates(
        students=MongoStudentRepository(db),
        resolve_default_program=ResolveDefaultActiveProgram(programs=MongoProgramRepository(db)),
        level_progress=MongoStudentLevelProgressRepository(db),
        skill_lookup=CurriculumSkillLookupAdapter(
            skill_repo=MongoSkillRepository(db), level_repo=MongoLevelRepository(db)
        ),
        criteria=MongoCriterionRepository(db),
    )
    return AiTechniqueComposition(
        draft_for_student=DraftTechniqueObservationForStudent(
            source=source,
            draft=DraftTechniqueObservation(
                llm=ai.llm, record_ai_call=ai.record_ai_call, entitlement=ai.entitlement
            ),
        ),
        enabled=not isinstance(ai.llm, DisabledLlmPort),
    )
