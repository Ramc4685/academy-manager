"""Composition helpers for curriculum and student_progress contexts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.v2.contexts.curriculum.application.use_cases.get_pathway import GetFullPathway
from backend.v2.contexts.curriculum.application.use_cases.manage_criteria import AddSkillCriterion
from backend.v2.contexts.curriculum.application.use_cases.manage_levels import (
    CreateLevel,
    ListLevels,
    UpdateLevel,
)
from backend.v2.contexts.curriculum.application.use_cases.manage_program import (
    CreateProgram,
    GetProgram,
    ListPrograms,
)
from backend.v2.contexts.curriculum.application.use_cases.manage_refs import AddExternalReference
from backend.v2.contexts.curriculum.application.use_cases.manage_skills import (
    CreateSkill,
    ListSkills,
    UpdateSkill,
)
from backend.v2.contexts.curriculum.application.use_cases.seed_curriculum import (
    seed_badminton_pathway,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_criterion_repo import (
    MongoCriterionRepository,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_ext_ref_repo import (
    MongoExternalRefRepository,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_level_repo import MongoLevelRepository
from backend.v2.contexts.curriculum.infrastructure.mongo_pathway_query import MongoPathwayQuery
from backend.v2.contexts.curriculum.infrastructure.mongo_program_repo import MongoProgramRepository
from backend.v2.contexts.curriculum.infrastructure.mongo_skill_repo import MongoSkillRepository
from backend.v2.contexts.student_progress.application.use_cases.get_certificates import (
    GetStudentCertificates,
)
from backend.v2.contexts.student_progress.application.use_cases.get_level_up_queue import (
    GetLevelUpQueue,
)
from backend.v2.contexts.student_progress.application.use_cases.get_passport import (
    GetStudentPassport,
)
from backend.v2.contexts.student_progress.application.use_cases.get_student_progress import (
    GetStudentProgress,
)
from backend.v2.contexts.student_progress.application.use_cases.place_student import (
    PlaceStudentInLevel,
)
from backend.v2.contexts.student_progress.application.use_cases.recommend_level_up import (
    RecommendLevelUp,
)
from backend.v2.contexts.student_progress.application.use_cases.record_test_attempt import (
    RecordTestAttempt,
)
from backend.v2.contexts.student_progress.application.use_cases.review_level_up import (
    ReviewLevelUpRecommendation,
)
from backend.v2.contexts.student_progress.application.use_cases.update_skill_status import (
    UpdateSkillStatus,
)
from backend.v2.contexts.student_progress.infrastructure.curriculum_lookup_adapter import (
    CurriculumSkillLookupAdapter as CurriculumSkillLookup,
)
from backend.v2.contexts.student_progress.infrastructure.mongo_certificate_repo import (
    MongoSkillCertificateRepository as MongoCertificateRepository,
)
from backend.v2.contexts.student_progress.infrastructure.mongo_level_progress_repo import (
    MongoStudentLevelProgressRepository as MongoLevelProgressRepository,
)
from backend.v2.contexts.student_progress.infrastructure.mongo_recommendation_repo import (
    MongoLevelUpRecommendationRepository as MongoRecommendationRepository,
)
from backend.v2.contexts.student_progress.infrastructure.mongo_skill_progress_repo import (
    MongoStudentSkillProgressRepository as MongoSkillProgressRepository,
)
from backend.v2.contexts.student_progress.infrastructure.mongo_test_attempt_repo import (
    MongoTestAttemptRepository,
)
from backend.v2.shared.config import get_settings

# ---------------------------------------------------------------------------
# SeedBadmintonPathway callable wrapper
# ---------------------------------------------------------------------------


class SeedBadmintonPathway:
    """Thin callable wrapper around seed_badminton_pathway."""

    def __init__(
        self,
        *,
        programs: MongoProgramRepository,
        levels: MongoLevelRepository,
        skills: MongoSkillRepository,
        criteria: MongoCriterionRepository,
        refs: MongoExternalRefRepository,
        academy_id: str,
    ) -> None:
        self._programs = programs
        self._levels = levels
        self._skills = skills
        self._criteria = criteria
        self._refs = refs
        self._academy_id = academy_id

    async def execute(self, *, created_by: str = "admin") -> object:
        return await seed_badminton_pathway(
            academy_id=self._academy_id,
            programs=self._programs,
            levels=self._levels,
            skills=self._skills,
            criteria=self._criteria,
            refs=self._refs,
            created_by=created_by,
        )


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class CurriculumComposition:
    create_program: CreateProgram
    list_programs: ListPrograms
    get_program: GetProgram
    create_level: CreateLevel
    update_level: UpdateLevel
    list_levels: ListLevels
    create_skill: CreateSkill
    update_skill: UpdateSkill
    list_skills: ListSkills
    add_criterion: AddSkillCriterion
    add_external_ref: AddExternalReference
    get_full_pathway: GetFullPathway
    seed_badminton: SeedBadmintonPathway


@dataclass
class StudentProgressComposition:
    place_student: PlaceStudentInLevel
    update_skill_status: UpdateSkillStatus
    record_test_attempt: RecordTestAttempt
    recommend_level_up: RecommendLevelUp
    review_level_up: ReviewLevelUpRecommendation
    get_student_progress: GetStudentProgress
    get_passport: GetStudentPassport
    get_level_up_queue: GetLevelUpQueue
    get_certificates: GetStudentCertificates


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------


def compose_curriculum(db: AsyncIOMotorDatabase[Any]) -> CurriculumComposition:
    settings = get_settings()
    academy_id = settings.default_academy_id

    programs_repo = MongoProgramRepository(db)
    levels_repo = MongoLevelRepository(db)
    skills_repo = MongoSkillRepository(db)
    criteria_repo = MongoCriterionRepository(db)
    refs_repo = MongoExternalRefRepository(db)
    pathway_query = MongoPathwayQuery(
        programs_repo,
        levels_repo,
        skills_repo,
        criteria_repo,
        refs_repo,
    )

    return CurriculumComposition(
        create_program=CreateProgram(programs=programs_repo),
        list_programs=ListPrograms(programs=programs_repo),
        get_program=GetProgram(programs=programs_repo),
        create_level=CreateLevel(programs=programs_repo, levels=levels_repo),
        update_level=UpdateLevel(levels=levels_repo),
        list_levels=ListLevels(levels=levels_repo),
        create_skill=CreateSkill(levels=levels_repo, skills=skills_repo),
        update_skill=UpdateSkill(skills=skills_repo),
        list_skills=ListSkills(skills=skills_repo),
        add_criterion=AddSkillCriterion(skills=skills_repo, criteria=criteria_repo),
        add_external_ref=AddExternalReference(skills=skills_repo, refs=refs_repo),
        get_full_pathway=GetFullPathway(pathway_query=pathway_query),
        seed_badminton=SeedBadmintonPathway(
            programs=programs_repo,
            levels=levels_repo,
            skills=skills_repo,
            criteria=criteria_repo,
            refs=refs_repo,
            academy_id=academy_id,
        ),
    )


def compose_student_progress(db: AsyncIOMotorDatabase[Any]) -> StudentProgressComposition:
    level_progress_repo = MongoLevelProgressRepository(db)
    skill_progress_repo = MongoSkillProgressRepository(db)
    test_attempt_repo = MongoTestAttemptRepository(db)
    recommendation_repo = MongoRecommendationRepository(db)
    certificate_repo = MongoCertificateRepository(db)
    skill_lookup = CurriculumSkillLookup(
        skill_repo=MongoSkillRepository(db),
        level_repo=MongoLevelRepository(db),
    )

    return StudentProgressComposition(
        place_student=PlaceStudentInLevel(
            level_progress=level_progress_repo,
            skill_progress=skill_progress_repo,
            skill_lookup=skill_lookup,
        ),
        update_skill_status=UpdateSkillStatus(
            level_progress=level_progress_repo,
            skill_progress=skill_progress_repo,
        ),
        record_test_attempt=RecordTestAttempt(
            test_attempts=test_attempt_repo,
            skill_progress=skill_progress_repo,
            level_progress=level_progress_repo,
            skill_lookup=skill_lookup,
        ),
        recommend_level_up=RecommendLevelUp(
            level_progress=level_progress_repo,
            skill_progress=skill_progress_repo,
            recommendations=recommendation_repo,
            skill_lookup=skill_lookup,
        ),
        review_level_up=ReviewLevelUpRecommendation(
            recommendations=recommendation_repo,
            level_progress=level_progress_repo,
            skill_progress=skill_progress_repo,
            certificates=certificate_repo,
            skill_lookup=skill_lookup,
        ),
        get_student_progress=GetStudentProgress(
            level_progress=level_progress_repo,
            skill_progress=skill_progress_repo,
            recommendations=recommendation_repo,
            certificates=certificate_repo,
            skill_lookup=skill_lookup,
        ),
        get_passport=GetStudentPassport(
            level_progress=level_progress_repo,
            skill_progress=skill_progress_repo,
            skill_lookup=skill_lookup,
            test_attempts=test_attempt_repo,
        ),
        get_level_up_queue=GetLevelUpQueue(
            level_progress=level_progress_repo,
            skill_progress=skill_progress_repo,
            recommendations=recommendation_repo,
            skill_lookup=skill_lookup,
        ),
        get_certificates=GetStudentCertificates(certificates=certificate_repo),
    )
