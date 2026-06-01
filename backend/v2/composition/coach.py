"""Compose coach BFF use cases from contexts + infrastructure."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.v2.contexts.coaching.application.use_cases.bulk_mark_attendance import (
    BulkMarkAttendance,
)
from backend.v2.contexts.coaching.application.use_cases.mark_attendance import MarkAttendance
from backend.v2.contexts.coaching.application.use_cases.session_notes import (
    CreateLessonPlan,
    CreateProgressNote,
    ListLessonPlans,
    ListProgressNotes,
)
from backend.v2.contexts.coaching.infrastructure.mongo_attendance_repo import (
    MongoAttendanceRepository,
)
from backend.v2.contexts.coaching.infrastructure.mongo_session_notes_repo import (
    MongoCoachingNotesRepository,
)
from backend.v2.contexts.enrollment.application.use_cases.coach_roster_writes import (
    CoachAddStudentToRoster,
    CoachRemoveStudentFromRoster,
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
from backend.v2.shared.events import Outbox
from backend.v2.shared.idempotency import IdempotencyStore

from .coaching_lookups import (
    EnrollmentLookupAdapter,
    EnrollmentOccurrenceLookup,
)


@dataclass
class CoachComposition:
    list_today: ListCoachOccurrencesForDate
    get_roster: GetSessionRoster
    mark_attendance: MarkAttendance
    bulk_mark_attendance: BulkMarkAttendance
    get_dashboard_metrics: object
    create_lesson_plan: CreateLessonPlan
    list_lesson_plans: ListLessonPlans
    create_progress_note: CreateProgressNote
    list_progress_notes: ListProgressNotes
    assigned_sessions: CoachAssignedSessionLookup
    add_student_to_roster: CoachAddStudentToRoster
    remove_student_from_roster: CoachRemoveStudentFromRoster


class CoachAssignedSessionLookup:
    def __init__(self, sessions: MongoSessionRepository) -> None:
        self._sessions = sessions

    async def is_coach_assigned(self, coach_id: str, session_id: str) -> bool:
        session = await self._sessions.get(session_id)
        return bool(session and session.coach_id == coach_id)


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
    occurrences_repo = MongoSessionOccurrenceRepository(db)
    notes_repo = MongoCoachingNotesRepository(db)
    assigned_sessions = CoachAssignedSessionLookup(sessions_repo)

    async def get_dashboard_metrics(coach_id: str) -> dict[str, int | float]:
        today = datetime.now(UTC).date()
        today_sessions = await sessions_repo.for_coach_on_date(coach_id, today)
        session_cursor = sessions_repo._find_many(  # type: ignore[attr-defined]
            {"coach_id": coach_id, "status": "scheduled"}
        )
        session_ids = [str(doc["session_id"]) async for doc in session_cursor]
        student_ids = (
            await enrollments_repo.collection.distinct(
                "student_id",
                {
                    "academy_id": settings.default_academy_id,
                    "session_id": {"$in": session_ids},
                    "status": "active",
                },
            )
            if session_ids
            else []
        )
        total_marks = await attendance_repo.collection.count_documents(
            {"academy_id": settings.default_academy_id, "marked_by": coach_id}
        )
        present_marks = await attendance_repo.collection.count_documents(
            {
                "academy_id": settings.default_academy_id,
                "marked_by": coach_id,
                "status": {"$in": ["present", "late"]},
            }
        )
        attendance_percentage = (
            round((present_marks / total_marks) * 100, 1) if total_marks else 0.0
        )
        return {
            "active_student_count": len(student_ids),
            "sessions_today": len(today_sessions),
            "attendance_percentage": attendance_percentage,
            "expected_cut_cents": present_marks * 3500,
            "marked_attendance_count": total_marks,
        }

    return CoachComposition(
        list_today=ListCoachOccurrencesForDate(
            occurrences=occurrences_repo, sessions=sessions_repo
        ),
        get_roster=GetSessionRoster(enrollments=enrollments_repo, students=students_repo),
        mark_attendance=MarkAttendance(
            attendance_repo=attendance_repo,
            occurrence_lookup=EnrollmentOccurrenceLookup(occurrences_repo),
            enrollment_lookup=EnrollmentLookupAdapter(enrollments_repo),
            outbox=outbox,
            idempotency_store=idempotency_store,
            academy_id=settings.default_academy_id,
        ),
        bulk_mark_attendance=BulkMarkAttendance(
            attendance_repo=attendance_repo,
            occurrence_lookup=EnrollmentOccurrenceLookup(occurrences_repo),
            enrollment_lookup=EnrollmentLookupAdapter(enrollments_repo),
            outbox=outbox,
            idempotency_store=idempotency_store,
            academy_id=settings.default_academy_id,
        ),
        get_dashboard_metrics=get_dashboard_metrics,
        create_lesson_plan=CreateLessonPlan(notes=notes_repo, sessions=assigned_sessions),
        list_lesson_plans=ListLessonPlans(notes=notes_repo, sessions=assigned_sessions),
        create_progress_note=CreateProgressNote(
            notes=notes_repo,
            sessions=assigned_sessions,
            enrollments=enrollments_repo,
        ),
        list_progress_notes=ListProgressNotes(notes=notes_repo, sessions=assigned_sessions),
        assigned_sessions=assigned_sessions,
        # TODO: academy_id is baked in at startup from default_academy_id.
        # This must be replaced with per-request tenant resolution before multi-tenant rollout.
        # See SaaS migration work: interfaces should derive academy_id from the authenticated user's membership.
        add_student_to_roster=CoachAddStudentToRoster(
            sessions=sessions_repo,
            enrollments=enrollments_repo,
            students=students_repo,
            assigned_sessions=assigned_sessions,
            academy_id=settings.default_academy_id,
        ),
        remove_student_from_roster=CoachRemoveStudentFromRoster(
            enrollments=enrollments_repo,
            assigned_sessions=assigned_sessions,
        ),
    )
