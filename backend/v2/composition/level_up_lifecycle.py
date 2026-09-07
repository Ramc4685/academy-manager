"""Level-up ⇄ enrollment lifecycle wiring (issue #673).

The student_progress context asks "does this student still attend?" through
its ``EnrollmentStatusLookup`` port. This module adapts that port to the
enrollment context's Mongo read (the same active-or-paused predicate the
coach passport uses, issue #651) and builds the use case the
``Enrollment.EnrollmentCancelled`` handler runs to expire stale
recommendations. Kept out of ``composition/admin.py`` (at its line cap) and
``composition/pathway.py`` stays a pure factory over it.
"""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_repo import (
    MongoEnrollmentRepository,
)
from backend.v2.contexts.student_progress.application.use_cases.expire_level_up_recommendations import (
    ExpireLevelUpRecommendations,
)
from backend.v2.contexts.student_progress.infrastructure.mongo_recommendation_repo import (
    MongoLevelUpRecommendationRepository,
)


class EnrollmentStatusAdapter:
    """``EnrollmentStatusLookup`` over the tenant-scoped enrollment repository.

    Both reads are scoped by the request/event tenant inside the repository;
    nothing is captured at composition time.
    """

    def __init__(self, enrollments: MongoEnrollmentRepository) -> None:
        self._enrollments = enrollments

    async def has_active_or_paused_enrollment(self, student_id: str) -> bool:
        return bool(await self._enrollments.active_or_paused_for_student(student_id))

    async def students_with_active_or_paused_enrollment(self, student_ids: list[str]) -> set[str]:
        return await self._enrollments.student_ids_with_active_or_paused_enrollment(student_ids)


def enrollment_status_lookup(db: AsyncIOMotorDatabase[Any]) -> EnrollmentStatusAdapter:
    return EnrollmentStatusAdapter(MongoEnrollmentRepository(db))


def compose_expire_level_up_recommendations(
    db: AsyncIOMotorDatabase[Any],
) -> ExpireLevelUpRecommendations:
    return ExpireLevelUpRecommendations(
        recommendations=MongoLevelUpRecommendationRepository(db),
        enrollment_lookup=enrollment_status_lookup(db),
    )
