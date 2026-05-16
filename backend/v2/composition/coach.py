"""Compose coach BFF use cases from contexts + infrastructure."""

from __future__ import annotations

from typing import Any

from dataclasses import dataclass

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.v2.contexts.coaching.application.use_cases.mark_attendance import MarkAttendance
from backend.v2.contexts.coaching.infrastructure.mongo_attendance_repo import (
    MongoAttendanceRepository,
)
from backend.v2.contexts.enrollment.application.use_cases.get_session_roster import (
    GetSessionRoster,
)
from backend.v2.contexts.enrollment.application.use_cases.list_coach_sessions_for_date import (
    ListCoachSessionsForDate,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_repo import (
    MongoEnrollmentRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_session_repo import (
    MongoSessionRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_student_repo import (
    MongoStudentRepository,
)
from backend.v2.shared.config import get_settings
from backend.v2.shared.events import Outbox
from backend.v2.shared.idempotency import IdempotencyStore

from .coaching_lookups import EnrollmentLookupAdapter, EnrollmentSessionLookup


@dataclass
class CoachComposition:
    list_today: ListCoachSessionsForDate
    get_roster: GetSessionRoster
    mark_attendance: MarkAttendance


def compose_coach(
    db: AsyncIOMotorDatabase[Any],
    outbox: Outbox,
    idempotency_store: IdempotencyStore,
) -> CoachComposition:
    settings = get_settings()
    sessions_repo = MongoSessionRepository(db)
    enrollments_repo = MongoEnrollmentRepository(db)
    students_repo = MongoStudentRepository(db)
    attendance_repo = MongoAttendanceRepository(db)

    return CoachComposition(
        list_today=ListCoachSessionsForDate(sessions=sessions_repo),
        get_roster=GetSessionRoster(enrollments=enrollments_repo, students=students_repo),
        mark_attendance=MarkAttendance(
            attendance_repo=attendance_repo,
            session_lookup=EnrollmentSessionLookup(sessions_repo),
            enrollment_lookup=EnrollmentLookupAdapter(enrollments_repo),
            outbox=outbox,
            idempotency_store=idempotency_store,
            academy_id=settings.default_academy_id,
        ),
    )
