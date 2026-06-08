"""MongoDB PathwayQuery — reads full program + levels + skills + criteria."""

from __future__ import annotations

from backend.v2.contexts.curriculum.domain.models import (
    FullPathway,
    PathwayLevel,
    SkillWithCriteria,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_criterion_repo import (
    MongoCriterionRepository,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_ext_ref_repo import (
    MongoExternalRefRepository,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_level_repo import MongoLevelRepository
from backend.v2.contexts.curriculum.infrastructure.mongo_program_repo import MongoProgramRepository
from backend.v2.contexts.curriculum.infrastructure.mongo_skill_repo import MongoSkillRepository


class MongoPathwayQuery:
    def __init__(
        self,
        programs: MongoProgramRepository,
        levels: MongoLevelRepository,
        skills: MongoSkillRepository,
        criteria: MongoCriterionRepository,
        ext_refs: MongoExternalRefRepository,
    ) -> None:
        self._programs = programs
        self._levels = levels
        self._skills = skills
        self._criteria = criteria
        self._ext_refs = ext_refs

    async def get_full_pathway(self, program_id: str) -> FullPathway | None:
        program = await self._programs.get(program_id)
        if program is None:
            return None

        level_list = await self._levels.list_for_program(program_id)
        pathway_levels: list[PathwayLevel] = []

        for level in level_list:
            skill_list = await self._skills.list_for_level(level.level_id)
            skills_with_criteria: list[SkillWithCriteria] = []

            for skill in skill_list:
                crit_list = await self._criteria.list_for_skill(skill.skill_id)
                ref_list = await self._ext_refs.list_for_skill(skill.skill_id)
                skills_with_criteria.append(
                    SkillWithCriteria(skill=skill, criteria=crit_list, external_refs=ref_list)
                )

            pathway_levels.append(PathwayLevel(level=level, skills=skills_with_criteria))

        return FullPathway(program=program, levels=pathway_levels)
