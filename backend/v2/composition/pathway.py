"""Composition helpers for curriculum and student_progress contexts."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.v2.composition.level_up_lifecycle import enrollment_status_lookup
from backend.v2.contexts.billing.infrastructure.mongo_billing_counter_repo import (
    MongoBillingCounterRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_settings_repo import (
    MongoBillingSettingsRepository,
)
from backend.v2.contexts.curriculum.application.use_cases.get_pathway import GetFullPathway
from backend.v2.contexts.curriculum.application.use_cases.manage_criteria import AddSkillCriterion
from backend.v2.contexts.curriculum.application.use_cases.manage_lesson_cards import (
    GetLessonCardForSkill,
    ListLessonCards,
)
from backend.v2.contexts.curriculum.application.use_cases.manage_levels import (
    CreateLevel,
    DeleteLevel,
    GetLevelUsage,
    ListLevels,
    ReorderLevels,
    UpdateLevel,
)
from backend.v2.contexts.curriculum.application.use_cases.manage_program import (
    CreateProgram,
    GetProgram,
    ListPrograms,
    ResolveDefaultActiveProgram,
)
from backend.v2.contexts.curriculum.application.use_cases.manage_refs import AddExternalReference
from backend.v2.contexts.curriculum.application.use_cases.manage_skills import (
    CreateSkill,
    ListSkills,
    ReorderSkills,
    UpdateSkill,
)
from backend.v2.contexts.curriculum.application.use_cases.seed_curriculum import (
    seed_badminton_pathway,
)
from backend.v2.contexts.curriculum.application.use_cases.seed_lesson_cards import (
    LessonCardSeedResult,
    seed_lesson_cards,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_criterion_repo import (
    MongoCriterionRepository,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_ext_ref_repo import (
    MongoExternalRefRepository,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_lesson_card_repo import (
    MongoLessonCardRepository,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_level_deletion_store import (
    MongoLevelDeletionStore,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_level_repo import MongoLevelRepository
from backend.v2.contexts.curriculum.infrastructure.mongo_pathway_query import MongoPathwayQuery
from backend.v2.contexts.curriculum.infrastructure.mongo_program_repo import MongoProgramRepository
from backend.v2.contexts.curriculum.infrastructure.mongo_skill_repo import MongoSkillRepository
from backend.v2.contexts.curriculum.infrastructure.mongo_video_ref_repo import (
    MongoCurriculumVideoRefRepository,
)
from backend.v2.contexts.student_progress.application.use_cases.auto_approve_level_ups import (
    AutoApproveLevelUps,
)
from backend.v2.contexts.student_progress.application.use_cases.certificate_share import (
    SetCertificateShare,
)
from backend.v2.contexts.student_progress.application.use_cases.curriculum_change_checks import (
    CurriculumChangeChecks,
)
from backend.v2.contexts.student_progress.application.use_cases.get_active_level_names import (
    GetActiveLevelNames,
)
from backend.v2.contexts.student_progress.application.use_cases.get_certificate_detail import (
    GetCertificateDetail,
)
from backend.v2.contexts.student_progress.application.use_cases.get_certificates import (
    GetStudentCertificates,
)
from backend.v2.contexts.student_progress.application.use_cases.get_level_up_queue import (
    GetLevelUpQueue,
)
from backend.v2.contexts.student_progress.application.use_cases.get_parent_journey import (
    GetParentJourney,
)
from backend.v2.contexts.student_progress.application.use_cases.get_passport import (
    GetStudentPassport,
)
from backend.v2.contexts.student_progress.application.use_cases.get_pathway_dashboard import (
    GetPathwayDashboard,
)
from backend.v2.contexts.student_progress.application.use_cases.get_pathway_placement import (
    GetStudentPathwayPlacement,
)
from backend.v2.contexts.student_progress.application.use_cases.get_progress_summary import (
    GetProgressSummary,
)
from backend.v2.contexts.student_progress.application.use_cases.get_recent_skill_updates import (
    GetInProgressSkills,
    GetRecentSkillUpdates,
)
from backend.v2.contexts.student_progress.application.use_cases.get_skill_board import (
    GetSkillBoard,
)
from backend.v2.contexts.student_progress.application.use_cases.get_student_progress import (
    GetStudentProgress,
)
from backend.v2.contexts.student_progress.application.use_cases.get_teaching_focus import (
    GetTeachingFocus,
)
from backend.v2.contexts.student_progress.application.use_cases.mark_skill_mastered import (
    MarkSkillMastered,
)
from backend.v2.contexts.student_progress.application.use_cases.place_student import (
    PlaceStudentInLevel,
)
from backend.v2.contexts.student_progress.application.use_cases.progress_milestones import (
    GetProgressSettings,
    RecordReachedMilestones,
    UpdateProgressSettings,
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
from backend.v2.contexts.student_progress.application.use_cases.revoke_certificate import (
    RevokeCertificate,
)
from backend.v2.contexts.student_progress.application.use_cases.set_mastery_note import (
    SetMasteryNote,
)
from backend.v2.contexts.student_progress.application.use_cases.unmark_skill_mastered import (
    UnmarkSkillMastered,
)
from backend.v2.contexts.student_progress.application.use_cases.update_skill_status import (
    UpdateSkillStatus,
)
from backend.v2.contexts.student_progress.domain.logic import format_cert_number
from backend.v2.contexts.student_progress.infrastructure.curriculum_lookup_adapter import (
    CurriculumSkillLookupAdapter as CurriculumSkillLookup,
)
from backend.v2.contexts.student_progress.infrastructure.mongo_certificate_audit import (
    MongoCertificateAuditLog,
)
from backend.v2.contexts.student_progress.infrastructure.mongo_certificate_repo import (
    MongoSkillCertificateRepository as MongoCertificateRepository,
)
from backend.v2.contexts.student_progress.infrastructure.mongo_level_progress_repo import (
    MongoStudentLevelProgressRepository as MongoLevelProgressRepository,
)
from backend.v2.contexts.student_progress.infrastructure.mongo_milestone_repo import (
    MongoStudentMilestoneRepository,
)
from backend.v2.contexts.student_progress.infrastructure.mongo_placement_audit import (
    MongoPlacementAuditLog,
)
from backend.v2.contexts.student_progress.infrastructure.mongo_progress_settings_repo import (
    MongoProgressSettingsRepository,
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
from backend.v2.shared.events import Outbox
from backend.v2.shared.idempotency import IdempotencyStore
from backend.v2.shared.tenancy import current_academy_id
from backend.v2.shared.tenancy.academy_url import academy_frontend_url

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
    ) -> None:
        self._programs = programs
        self._levels = levels
        self._skills = skills
        self._criteria = criteria
        self._refs = refs

    async def execute(self, *, created_by: str = "admin") -> object:
        return await seed_badminton_pathway(
            academy_id=current_academy_id(),
            programs=self._programs,
            levels=self._levels,
            skills=self._skills,
            criteria=self._criteria,
            refs=self._refs,
            created_by=created_by,
        )


class SeedLessonCards:
    """Thin callable wrapper around seed_lesson_cards."""

    def __init__(
        self,
        *,
        programs: MongoProgramRepository,
        levels: MongoLevelRepository,
        skills: MongoSkillRepository,
        cards: MongoLessonCardRepository,
        video_refs: MongoCurriculumVideoRefRepository,
    ) -> None:
        self._programs = programs
        self._levels = levels
        self._skills = skills
        self._cards = cards
        self._video_refs = video_refs

    async def execute(
        self, *, program_id: str | None = None, created_by: str = "admin"
    ) -> LessonCardSeedResult:
        return await seed_lesson_cards(
            academy_id=current_academy_id(),
            programs=self._programs,
            levels=self._levels,
            skills=self._skills,
            cards=self._cards,
            video_refs=self._video_refs,
            created_by=created_by,
            program_id=program_id,
        )


class CertificateNumberAdapter:
    """``CertificateNumbers`` over the academy's billing counter and invoice prefix.

    Both repositories read the tenant at call time; the counter's ``$inc`` is
    what keeps concurrent approvals from sharing a number.
    """

    def __init__(
        self, counters: MongoBillingCounterRepository, settings: MongoBillingSettingsRepository
    ) -> None:
        self._counters = counters
        self._settings = settings

    async def next_number(self) -> str:
        prefix = (await self._settings.get()).invoice_number_prefix
        return format_cert_number(prefix, await self._counters.next_value(scope="certificate"))


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class CurriculumComposition:
    create_program: CreateProgram
    list_programs: ListPrograms
    resolve_default_program: ResolveDefaultActiveProgram
    get_program: GetProgram
    create_level: CreateLevel
    update_level: UpdateLevel
    delete_level: DeleteLevel
    get_level_usage: GetLevelUsage
    list_levels: ListLevels
    create_skill: CreateSkill
    update_skill: UpdateSkill
    list_skills: ListSkills
    reorder_levels: ReorderLevels
    reorder_skills: ReorderSkills
    add_criterion: AddSkillCriterion
    add_external_ref: AddExternalReference
    get_full_pathway: GetFullPathway
    seed_badminton: SeedBadmintonPathway
    seed_lesson_cards: SeedLessonCards
    list_lesson_cards: ListLessonCards
    get_lesson_card_for_skill: GetLessonCardForSkill


@dataclass
class StudentProgressComposition:
    place_student: PlaceStudentInLevel
    update_skill_status: UpdateSkillStatus
    record_test_attempt: RecordTestAttempt
    recommend_level_up: RecommendLevelUp
    review_level_up: ReviewLevelUpRecommendation
    get_pathway_placement: GetStudentPathwayPlacement
    get_student_progress: GetStudentProgress
    get_progress_summary: GetProgressSummary
    get_passport: GetStudentPassport
    get_level_up_queue: GetLevelUpQueue
    get_certificates: GetStudentCertificates
    get_certificate_detail: GetCertificateDetail
    revoke_certificate: RevokeCertificate
    get_skill_board: GetSkillBoard
    get_active_level_names: GetActiveLevelNames
    get_teaching_focus: GetTeachingFocus
    get_recent_skill_updates: GetRecentSkillUpdates
    get_in_progress_skills: GetInProgressSkills
    get_parent_journey: GetParentJourney
    mark_skill_mastered: MarkSkillMastered
    unmark_skill_mastered: UnmarkSkillMastered
    set_mastery_note: SetMasteryNote
    auto_approve_level_ups: AutoApproveLevelUps
    get_pathway_dashboard: GetPathwayDashboard
    curriculum_change_checks: CurriculumChangeChecks
    # L5B PR2: parent share links, progress settings, milestone records.
    set_certificate_share: SetCertificateShare
    get_progress_settings: GetProgressSettings
    update_progress_settings: UpdateProgressSettings
    record_milestones: RecordReachedMilestones
    #: ``(academy_id, token) -> https://<slug>.<apex>/c/<token>``: the academy's
    #: own host, never the product host (where ``/c/`` is a 404).
    certificate_share_url: Callable[[str, str], Awaitable[str]]


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------


def compose_curriculum(db: AsyncIOMotorDatabase[Any]) -> CurriculumComposition:
    programs_repo = MongoProgramRepository(db)
    levels_repo = MongoLevelRepository(db)
    skills_repo = MongoSkillRepository(db)
    criteria_repo = MongoCriterionRepository(db)
    refs_repo = MongoExternalRefRepository(db)
    lesson_card_repo = MongoLessonCardRepository(db)
    video_ref_repo = MongoCurriculumVideoRefRepository(db)
    level_deletion_store = MongoLevelDeletionStore(db)
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
        resolve_default_program=ResolveDefaultActiveProgram(programs=programs_repo),
        get_program=GetProgram(programs=programs_repo),
        create_level=CreateLevel(programs=programs_repo, levels=levels_repo),
        update_level=UpdateLevel(levels=levels_repo),
        delete_level=DeleteLevel(levels=levels_repo, store=level_deletion_store),
        get_level_usage=GetLevelUsage(levels=levels_repo, store=level_deletion_store),
        list_levels=ListLevels(levels=levels_repo),
        create_skill=CreateSkill(levels=levels_repo, skills=skills_repo),
        update_skill=UpdateSkill(skills=skills_repo),
        list_skills=ListSkills(skills=skills_repo),
        reorder_levels=ReorderLevels(levels=levels_repo),
        reorder_skills=ReorderSkills(skills=skills_repo),
        add_criterion=AddSkillCriterion(skills=skills_repo, criteria=criteria_repo),
        add_external_ref=AddExternalReference(skills=skills_repo, refs=refs_repo),
        get_full_pathway=GetFullPathway(pathway_query=pathway_query),
        seed_badminton=SeedBadmintonPathway(
            programs=programs_repo,
            levels=levels_repo,
            skills=skills_repo,
            criteria=criteria_repo,
            refs=refs_repo,
        ),
        seed_lesson_cards=SeedLessonCards(
            programs=programs_repo,
            levels=levels_repo,
            skills=skills_repo,
            cards=lesson_card_repo,
            video_refs=video_ref_repo,
        ),
        list_lesson_cards=ListLessonCards(cards=lesson_card_repo),
        get_lesson_card_for_skill=GetLessonCardForSkill(cards=lesson_card_repo),
    )


def compose_student_progress(
    db: AsyncIOMotorDatabase[Any],
    outbox: Outbox | None = None,
    idempotency_store: IdempotencyStore | None = None,
) -> StudentProgressComposition:
    level_progress_repo = MongoLevelProgressRepository(db)
    skill_progress_repo = MongoSkillProgressRepository(db)
    test_attempt_repo = MongoTestAttemptRepository(db)
    recommendation_repo = MongoRecommendationRepository(db)
    certificate_repo = MongoCertificateRepository(db)
    progress_audit = MongoCertificateAuditLog(db)
    progress_settings = MongoProgressSettingsRepository(db)
    skill_lookup = CurriculumSkillLookup(
        skill_repo=MongoSkillRepository(db),
        level_repo=MongoLevelRepository(db),
    )
    # Issue #673: recommend / approve / queue consult enrollment lifecycle.
    enrollment_lookup = enrollment_status_lookup(db)
    record_test_attempt = RecordTestAttempt(
        test_attempts=test_attempt_repo,
        skill_progress=skill_progress_repo,
        level_progress=level_progress_repo,
        skill_lookup=skill_lookup,
        outbox=outbox,
        idempotency_store=idempotency_store,
    )
    recommend_level_up = RecommendLevelUp(
        level_progress=level_progress_repo,
        skill_progress=skill_progress_repo,
        recommendations=recommendation_repo,
        skill_lookup=skill_lookup,
        enrollment_lookup=enrollment_lookup,
        outbox=outbox,
    )
    review_level_up = ReviewLevelUpRecommendation(
        recommendations=recommendation_repo,
        level_progress=level_progress_repo,
        skill_progress=skill_progress_repo,
        certificates=certificate_repo,
        cert_numbers=CertificateNumberAdapter(
            MongoBillingCounterRepository(db), MongoBillingSettingsRepository(db)
        ),
        skill_lookup=skill_lookup,
        enrollment_lookup=enrollment_lookup,
        outbox=outbox,
    )

    return StudentProgressComposition(
        place_student=PlaceStudentInLevel(
            level_progress=level_progress_repo,
            skill_progress=skill_progress_repo,
            skill_lookup=skill_lookup,
            recommendations=recommendation_repo,
            enrollment_lookup=enrollment_lookup,
            outbox=outbox,
            audit=MongoPlacementAuditLog(db),
        ),
        update_skill_status=UpdateSkillStatus(
            level_progress=level_progress_repo,
            skill_progress=skill_progress_repo,
            skill_lookup=skill_lookup,
            outbox=outbox,
        ),
        record_test_attempt=record_test_attempt,
        recommend_level_up=recommend_level_up,
        review_level_up=review_level_up,
        get_pathway_placement=GetStudentPathwayPlacement(
            level_progress=level_progress_repo,
            skill_progress=skill_progress_repo,
            skill_lookup=skill_lookup,
        ),
        get_student_progress=GetStudentProgress(
            level_progress=level_progress_repo,
            skill_progress=skill_progress_repo,
            recommendations=recommendation_repo,
            certificates=certificate_repo,
            skill_lookup=skill_lookup,
        ),
        get_progress_summary=GetProgressSummary(
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
            enrollment_lookup=enrollment_lookup,
        ),
        get_certificates=GetStudentCertificates(certificates=certificate_repo),
        get_certificate_detail=GetCertificateDetail(
            certificates=certificate_repo, skill_lookup=skill_lookup
        ),
        revoke_certificate=RevokeCertificate(certificates=certificate_repo, audit=progress_audit),
        get_active_level_names=GetActiveLevelNames(
            level_progress=level_progress_repo, skill_lookup=skill_lookup
        ),
        get_skill_board=GetSkillBoard(
            level_progress=level_progress_repo,
            skill_progress=skill_progress_repo,
            recommendations=recommendation_repo,
            skill_lookup=skill_lookup,
            criteria=MongoCriterionRepository(db),
        ),
        get_teaching_focus=GetTeachingFocus(
            level_progress=level_progress_repo,
            skill_progress=skill_progress_repo,
            skill_lookup=skill_lookup,
        ),
        get_recent_skill_updates=GetRecentSkillUpdates(
            skill_progress=skill_progress_repo,
            skill_lookup=skill_lookup,
        ),
        get_in_progress_skills=GetInProgressSkills(
            skill_progress=skill_progress_repo,
            skill_lookup=skill_lookup,
        ),
        get_parent_journey=GetParentJourney(
            level_progress=level_progress_repo,
            skill_progress=skill_progress_repo,
            skill_lookup=skill_lookup,
            certificates=certificate_repo,
            test_attempts=test_attempt_repo,
        ),
        mark_skill_mastered=MarkSkillMastered(
            level_progress=level_progress_repo,
            skill_progress=skill_progress_repo,
            skill_lookup=skill_lookup,
            record_test_attempt=record_test_attempt,
            recommend_level_up=recommend_level_up,
        ),
        unmark_skill_mastered=UnmarkSkillMastered(
            level_progress=level_progress_repo,
            skill_progress=skill_progress_repo,
            recommendations=recommendation_repo,
            skill_lookup=skill_lookup,
            test_attempts=test_attempt_repo,
            outbox=outbox,
        ),
        set_mastery_note=SetMasteryNote(skill_progress=skill_progress_repo),
        auto_approve_level_ups=AutoApproveLevelUps(
            recommendations=recommendation_repo,
            skill_progress=skill_progress_repo,
            skill_lookup=skill_lookup,
            review_level_up=review_level_up,
        ),
        get_pathway_dashboard=GetPathwayDashboard(
            level_progress=level_progress_repo,
            skill_progress=skill_progress_repo,
            recommendations=recommendation_repo,
            certificates=certificate_repo,
            levels=skill_lookup,
        ),
        curriculum_change_checks=CurriculumChangeChecks(
            level_progress=level_progress_repo,
            skill_progress=skill_progress_repo,
            skill_lookup=skill_lookup,
            recommendations=recommendation_repo,
            recommend_level_up=recommend_level_up,
        ),
        set_certificate_share=SetCertificateShare(
            certificates=certificate_repo, audit=progress_audit
        ),
        get_progress_settings=GetProgressSettings(settings=progress_settings),
        update_progress_settings=UpdateProgressSettings(
            settings=progress_settings, audit=progress_audit
        ),
        record_milestones=compose_record_milestones(db),
        certificate_share_url=_certificate_share_url(db),
    )


def _certificate_share_url(
    db: AsyncIOMotorDatabase[Any],
) -> Callable[[str, str], Awaitable[str]]:
    frontend_url = get_settings().frontend_url

    async def share_url(academy_id: str, token: str) -> str:
        doc = await db["academies"].find_one({"academy_id": academy_id}, {"slug": 1})
        base = academy_frontend_url(
            frontend_url=frontend_url, academy_slug=str((doc or {}).get("slug") or "")
        )
        return f"{base}/c/{quote(token, safe='')}"

    return share_url


def compose_record_milestones(db: AsyncIOMotorDatabase[Any]) -> RecordReachedMilestones:
    """Shared by the parent journey and the evening wins email."""
    return RecordReachedMilestones(
        settings=MongoProgressSettingsRepository(db),
        skill_progress=MongoSkillProgressRepository(db),
        certificates=MongoCertificateRepository(db),
        milestones=MongoStudentMilestoneRepository(db),
    )
