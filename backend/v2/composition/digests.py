"""Compose SendCoachDailyDigest from the communications + coaching contexts.

The plan generator is reused verbatim from Phase 2 (no new plan logic). It is
wrapped in a duck-typed ``plan_provider`` that first resolves the academy's
default program — mirroring the coach BFF route's graceful resolution — so a
missing pathway degrades to an all-unplaced plan instead of raising.

Email safety: the same Resend/Stub gating as ``compose_admin`` — the real
Resend adapter is only wired when ``email_delivery_enabled`` and a
``resend_api_key`` are both set; otherwise a stub records sends without
contacting a provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.v2.composition.pathway import (
    CurriculumComposition,
    compose_curriculum,
    compose_student_progress,
)
from backend.v2.contexts.coaching.application.use_cases.generate_daily_teaching_plan import (
    GenerateDailyTeachingPlan,
)
from backend.v2.contexts.communications.application.use_cases.get_digest_delivery_log import (
    GetDigestDeliveryLog,
)
from backend.v2.contexts.communications.application.use_cases.send_coach_daily_digest import (
    SendCoachDailyDigest,
)
from backend.v2.contexts.communications.application.use_cases.send_coach_digest_test import (
    SendCoachDigestTest,
)
from backend.v2.contexts.communications.infrastructure.mongo_audience_resolver import (
    MongoAudienceResolver,
)
from backend.v2.contexts.communications.infrastructure.mongo_digest_send_repo import (
    MongoDigestSendRepository,
)
from backend.v2.contexts.communications.infrastructure.resend_send_port import (
    ResendEmailSendPort,
)
from backend.v2.contexts.communications.infrastructure.stub_send_port import (
    StubEmailSendPort,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_criterion_repo import (
    MongoCriterionRepository,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_lesson_card_repo import (
    MongoLessonCardRepository,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_video_ref_repo import (
    MongoCurriculumVideoRefRepository,
)
from backend.v2.contexts.enrollment.application.use_cases.get_session_roster import (
    GetSessionRoster,
)
from backend.v2.contexts.enrollment.application.use_cases.list_coach_occurrences_for_date import (
    ListCoachOccurrencesForDate,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_repo import (
    MongoEnrollmentRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_occurrence_repo import (
    MongoSessionOccurrenceRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_session_repo import (
    MongoSessionRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_student_repo import (
    MongoStudentRepository,
)
from backend.v2.shared.config import get_settings


@dataclass(frozen=True, slots=True)
class ResolvedDigestSchedule:
    """Effective coach-digest schedule for one academy.

    ``enabled``/``hour`` are the *effective* values the hourly scheduler acts on
    after merging the per-academy notification override with the env fallback.
    """

    enabled: bool
    hour: int


def resolve_digest_schedule(
    *,
    academy_enabled: bool | None,
    academy_hour: int | None,
    env_enabled: bool,
    env_hour: int,
) -> ResolvedDigestSchedule:
    """Merge a per-academy override with the deprecated env fallback.

    Pure (no I/O, no APScheduler) so the resolution rule is unit-testable in
    isolation. The per-academy value wins when present; otherwise we fall back
    to the env default, preserving the original behaviour for any deployment
    that has not yet saved per-academy values.

    Note: ``hour`` is interpreted in the *scheduler* timezone, not the academy's
    local timezone — interpreting it per-academy is explicit future work.
    """
    enabled = env_enabled if academy_enabled is None else academy_enabled
    hour = env_hour if academy_hour is None else academy_hour
    if not (0 <= hour <= 23):
        hour = env_hour
    return ResolvedDigestSchedule(enabled=bool(enabled), hour=int(hour))


def _id_of(program: Any) -> str:
    if hasattr(program, "model_dump"):
        return str(program.model_dump().get("program_id", ""))
    return str(getattr(program, "program_id", ""))


def _name_of(program: Any) -> str:
    if hasattr(program, "model_dump"):
        return str(program.model_dump().get("name", "") or "")
    return str(getattr(program, "name", "") or "")


class _CoachDigestPlanProvider:
    """Wraps GenerateDailyTeachingPlan; resolves the default program first.

    Crosses into the coaching context only at the composition root — the
    digest use case itself stays context-agnostic (ADR-0005).
    """

    def __init__(
        self,
        *,
        generate: GenerateDailyTeachingPlan,
        curriculum: CurriculumComposition,
    ) -> None:
        self._generate = generate
        self._curriculum = curriculum

    async def execute(self, coach_id: str, on_date: date) -> Any | None:
        program_id, program_name = await self._resolve_program()
        return await self._generate.execute(
            coach_id=coach_id,
            on_date=on_date,
            program_id=program_id,
            program_name=program_name,
        )

    async def _resolve_program(self) -> tuple[str | None, str]:
        try:
            program = await self._curriculum.resolve_default_program.execute()
        except Exception:
            return None, ""
        program_id = _id_of(program)
        if not program_id:
            return None, ""
        name = ""
        try:
            full = await self._curriculum.get_program.execute(program_id)
            if full is not None:
                name = _name_of(full)
        except Exception:
            name = ""
        return program_id, name


@dataclass(frozen=True, slots=True)
class _DigestParts:
    """Shared collaborators for the daily + test coach-digest use cases."""

    digests: MongoDigestSendRepository
    resolver: MongoAudienceResolver
    sender: Any
    plan_provider: _CoachDigestPlanProvider


def _build_digest_parts(db: AsyncIOMotorDatabase[Any]) -> _DigestParts:
    settings = get_settings()

    occurrences_repo = MongoSessionOccurrenceRepository(db)
    sessions_repo = MongoSessionRepository(db)
    enrollments_repo = MongoEnrollmentRepository(db)
    students_repo = MongoStudentRepository(db)
    curriculum = compose_curriculum(db)
    student_progress = compose_student_progress(db)

    generate = GenerateDailyTeachingPlan(
        occurrences=ListCoachOccurrencesForDate(
            occurrences=occurrences_repo, sessions=sessions_repo
        ),
        get_roster=GetSessionRoster(enrollments=enrollments_repo, students=students_repo),
        teaching_focus=student_progress.get_teaching_focus,
        lesson_cards=MongoLessonCardRepository(db),
        video_refs=MongoCurriculumVideoRefRepository(db),
        criteria=MongoCriterionRepository(db),
    )
    plan_provider = _CoachDigestPlanProvider(generate=generate, curriculum=curriculum)

    from_address = (
        f"noreply@{settings.frontend_url.replace('https://', '').replace('http://', '').split('/')[0]}"
        if settings.frontend_url
        else "noreply@academy.app"
    )
    if settings.email_delivery_enabled and settings.resend_api_key:
        sender: Any = ResendEmailSendPort(
            api_key=settings.resend_api_key, from_address=from_address
        )
    else:
        sender = StubEmailSendPort()

    return _DigestParts(
        digests=MongoDigestSendRepository(db),
        resolver=MongoAudienceResolver(db=db),
        sender=sender,
        plan_provider=plan_provider,
    )


def compose_send_coach_daily_digest(db: AsyncIOMotorDatabase[Any]) -> SendCoachDailyDigest:
    parts = _build_digest_parts(db)
    return SendCoachDailyDigest(
        digests=parts.digests,
        resolver=parts.resolver,
        sender=parts.sender,
        plan_provider=parts.plan_provider,
    )


def compose_send_coach_digest_test(db: AsyncIOMotorDatabase[Any]) -> SendCoachDigestTest:
    parts = _build_digest_parts(db)
    return SendCoachDigestTest(
        digests=parts.digests,
        resolver=parts.resolver,
        sender=parts.sender,
        plan_provider=parts.plan_provider,
    )


def compose_get_digest_delivery_log(db: AsyncIOMotorDatabase[Any]) -> GetDigestDeliveryLog:
    return GetDigestDeliveryLog(digests=MongoDigestSendRepository(db))
