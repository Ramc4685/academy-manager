"""Compose coach BFF use cases from contexts + infrastructure."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.v2.composition.pathway import (
    CurriculumComposition,
    StudentProgressComposition,
    compose_curriculum,
    compose_student_progress,
)
from backend.v2.contexts.billing.application.ports import StripeGateway
from backend.v2.contexts.billing.application.use_cases.session_type_ops import (
    ListSessionTypes,
    ListStudentBillingEnrollments,
    MoveStudentSessionType,
    PreviewStudentSessionTypeMove,
)
from backend.v2.contexts.billing.infrastructure.mongo_session_type_repo import (
    MongoSessionTypeRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_student_billing_enrollment_repo import (
    MongoStudentBillingEnrollmentRepository,
)
from backend.v2.contexts.coaching.application.use_cases.bulk_mark_attendance import (
    BulkMarkAttendance,
)
from backend.v2.contexts.coaching.application.use_cases.mark_attendance import MarkAttendance
from backend.v2.contexts.coaching.application.use_cases.session_feedback import (
    CreateSessionFeedback,
    ListSessionFeedback,
)
from backend.v2.contexts.coaching.application.use_cases.session_notes import (
    CreateLessonPlan,
    CreateProgressNote,
    ListLessonPlans,
    ListProgressNotes,
)
from backend.v2.contexts.coaching.application.use_cases.skill_notes import (
    CreateSkillNote,
    ListSkillNotes,
)
from backend.v2.contexts.coaching.infrastructure.mongo_attendance_repo import (
    MongoAttendanceRepository,
)
from backend.v2.contexts.coaching.infrastructure.mongo_session_feedback_repo import (
    MongoSessionFeedbackRepository,
)
from backend.v2.contexts.coaching.infrastructure.mongo_session_notes_repo import (
    MongoCoachingNotesRepository,
)
from backend.v2.contexts.coaching.infrastructure.mongo_skill_note_repo import (
    MongoSkillNoteRepository,
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
    ListCoachUpcomingOccurrences,
)
from backend.v2.contexts.enrollment.domain.events import (
    StudentSessionTypeChanged,
    StudentSessionTypeChangedPayload,
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
from backend.v2.contexts.identity.application.use_cases.admin_directory import (
    UpdateAdminUserCommand,
)
from backend.v2.contexts.identity.infrastructure.mongo_user_repo import MongoUserRepository
from backend.v2.interfaces.coach.views import CoachProfileResponse, UpdateCoachProfileRequest
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
    create_feedback: CreateSessionFeedback
    list_feedback: ListSessionFeedback
    # Phase 2 — billing enrollment move surface
    list_billing_enrollments: ListStudentBillingEnrollments
    preview_student_session_type_move: PreviewStudentSessionTypeMove
    move_student_session_type: MoveStudentSessionType
    list_session_types: ListSessionTypes
    get_billing_enrollment: object  # Callable[[str], Awaitable[StudentBillingEnrollment | None]]
    get_active_session_enrollments_for_student: (
        object  # Callable[[str], Awaitable[list[Enrollment]]]
    )
    list_all_sessions: object  # Callable[[str], Awaitable[list[Session]]]
    get_profile: object  # Callable[[str], Awaitable[CoachProfileResponse | None]]
    update_profile: (
        object  # Callable[[str, body, academy_id], Awaitable[CoachProfileResponse | None]]
    )
    # Skill pathway surface
    create_skill_note: CreateSkillNote
    list_skill_notes: ListSkillNotes
    student_progress: StudentProgressComposition
    curriculum: CurriculumComposition


class CoachAssignedSessionLookup:
    def __init__(self, sessions: MongoSessionRepository) -> None:
        self._sessions = sessions

    async def is_coach_assigned(self, coach_id: str, session_id: str) -> bool:
        session = await self._sessions.get(session_id)
        return bool(session and session.coach_id == coach_id)


class _SessionTypeChangedEventSink:
    def __init__(self, outbox: Outbox) -> None:
        self._outbox = outbox

    async def record_session_type_changed(
        self,
        *,
        academy_id: str,
        enrollment_id: str,
        student_id: str,
        parent_id: str,
        from_session_type_id: str | None,
        to_session_type_id: str,
        net_cents: int,
        actor_id: str,
        reason: str | None,
    ) -> None:
        await self._outbox.append(
            StudentSessionTypeChanged(
                aggregate_id=enrollment_id,
                academy_id=academy_id,
                payload=StudentSessionTypeChangedPayload(
                    enrollment_id=enrollment_id,
                    student_id=student_id,
                    parent_id=parent_id,
                    from_session_type_id=from_session_type_id,
                    to_session_type_id=to_session_type_id,
                    net_cents=net_cents,
                    actor_id=actor_id,
                    reason=reason,
                ),
            )
        )


def compose_coach(
    db: AsyncIOMotorDatabase[Any],
    outbox: Outbox,
    idempotency_store: IdempotencyStore,
    stripe: StripeGateway,
) -> CoachComposition:
    settings = get_settings()
    sessions_repo = MongoSessionRepository(db)
    user_repo = MongoUserRepository(db, default_academy_id=settings.default_academy_id)
    enrollments_repo = MongoEnrollmentRepository(db)
    students_repo = MongoStudentRepository(db)
    attendance_repo = MongoAttendanceRepository(db)
    occurrences_repo = MongoSessionOccurrenceRepository(db)
    notes_repo = MongoCoachingNotesRepository(db)
    feedback_repo = MongoSessionFeedbackRepository(db)
    assigned_sessions = CoachAssignedSessionLookup(sessions_repo)
    # Billing repos for session-type move surface
    session_type_repo = MongoSessionTypeRepository(db)
    billing_enrollment_repo = MongoStudentBillingEnrollmentRepository(db)
    # Skill note repo
    skill_note_repo = MongoSkillNoteRepository(db)

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

    async def get_profile(user_id: str) -> CoachProfileResponse | None:
        user = await user_repo.get_by_id(user_id)
        if user is None:
            return None
        return CoachProfileResponse(
            user_id=user.user_id,
            display_name=user.display_name,
            email=str(user.email),
            phone=user.phone,
        )

    async def update_profile(
        user_id: str,
        body: UpdateCoachProfileRequest,
        *,
        academy_id: str,
    ) -> CoachProfileResponse | None:
        command = UpdateAdminUserCommand(
            email=body.email,  # type: ignore[arg-type]
            display_name=body.display_name,
            phone=body.phone,
            actor_id=user_id,
            reason="self-service profile update",
        )
        result = await user_repo.update_admin_user(user_id, command, academy_id=academy_id)
        if result is None:
            return None
        return CoachProfileResponse(
            user_id=result.user_id,
            display_name=result.display_name,
            email=str(result.email),
            phone=result.phone,
        )

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
        create_feedback=CreateSessionFeedback(
            feedback_repo=feedback_repo,
            assignment_lookup=assigned_sessions,
            outbox=outbox,
        ),
        list_feedback=ListSessionFeedback(feedback_repo=feedback_repo),
        # Phase 2 — billing enrollment move surface
        list_billing_enrollments=ListStudentBillingEnrollments(enrollments=billing_enrollment_repo),
        preview_student_session_type_move=PreviewStudentSessionTypeMove(
            enrollments=billing_enrollment_repo,
            session_types=session_type_repo,
        ),
        move_student_session_type=MoveStudentSessionType(
            enrollments=billing_enrollment_repo,
            session_types=session_type_repo,
            stripe=stripe,
            event_sink=_SessionTypeChangedEventSink(outbox),
        ),
        list_session_types=ListSessionTypes(session_types=session_type_repo),
        get_billing_enrollment=billing_enrollment_repo.get,
        get_active_session_enrollments_for_student=enrollments_repo.active_for_student,
        list_all_sessions=ListCoachUpcomingOccurrences(
            occurrences=occurrences_repo,
            sessions=sessions_repo,
        ).execute,
        get_profile=get_profile,
        update_profile=update_profile,
        # Skill pathway
        create_skill_note=CreateSkillNote(notes=skill_note_repo),
        list_skill_notes=ListSkillNotes(notes=skill_note_repo),
        student_progress=compose_student_progress(db, outbox),
        curriculum=compose_curriculum(db),
    )
