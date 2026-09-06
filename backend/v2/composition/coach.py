"""Compose coach BFF use cases from contexts + infrastructure."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
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
from backend.v2.composition.session_announcements import compose_announcements
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
from backend.v2.contexts.coaching.application.use_cases.correct_attendance import (
    CorrectAttendance,
)
from backend.v2.contexts.coaching.application.use_cases.generate_daily_teaching_plan import (
    GenerateDailyTeachingPlan,
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
    SetProgressNoteVisibility,
)
from backend.v2.contexts.coaching.application.use_cases.skill_notes import (
    CreateSkillNote,
    ListSkillNotes,
    SetSkillNoteVisibility,
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
from backend.v2.contexts.curriculum.infrastructure.mongo_criterion_repo import (
    MongoCriterionRepository,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_lesson_card_repo import (
    MongoLessonCardRepository,
)
from backend.v2.contexts.curriculum.infrastructure.mongo_video_ref_repo import (
    MongoCurriculumVideoRefRepository,
)
from backend.v2.contexts.enrollment.application.use_cases.coach_roster_writes import (
    CoachAddStudentToRoster,
    CoachRemoveStudentFromRoster,
)
from backend.v2.contexts.enrollment.application.use_cases.get_occurrence_roster import (
    GetOccurrenceRoster,
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
from backend.v2.contexts.enrollment.infrastructure.mongo_absence_notice_repo import (
    MongoAbsenceNoticeRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_repo import (
    MongoEnrollmentRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_occurrence_repo import (
    MongoSessionOccurrenceRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_occurrence_roster_repo import (
    MongoOccurrenceRosterRepository,
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
from backend.v2.contexts.identity.domain.identity_aliases import identity_aliases
from backend.v2.contexts.identity.infrastructure.mongo_membership_repo import (
    MongoMembershipRepository,
)
from backend.v2.contexts.identity.infrastructure.mongo_user_repo import MongoUserRepository
from backend.v2.interfaces.coach.views import CoachProfileResponse, UpdateCoachProfileRequest
from backend.v2.shared.comms import CommsService, Message, MongoMessageRepository
from backend.v2.shared.config import get_settings
from backend.v2.shared.events import Outbox
from backend.v2.shared.http.persona import COACH_SUPERVISOR_ROLES
from backend.v2.shared.idempotency import IdempotencyStore
from backend.v2.shared.tenancy import TenantContextUnset, current_academy_id
from backend.v2.shared.time import academy_timezone_lookup

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
    # Coach daily teaching plan (lesson guidance)
    generate_daily_teaching_plan: GenerateDailyTeachingPlan
    # Callable[[str], Awaitable[list[Attendance]]] — existing student marks for
    # one occurrence, so /coach/today can hydrate attendance state on reload.
    # Optional default keeps hand-built test compositions working.
    list_attendance_for_occurrence: object = None
    # Occurrence-scoped roster (expected-absence flags + one-time makeup/
    # trial entries) for /coach/today.
    get_occurrence_roster: GetOccurrenceRoster | None = None
    # Messages inbox (UIM13)
    list_messages: object = None  # Callable[[str], Awaitable[list[Message]]]
    mark_message_read: object = None  # Callable[[str, str], Awaitable[None]]
    # Callable[[str], Awaitable[str | None]] — IANA timezone name for an
    # academy, so /coach/today can default "today" to the academy-local
    # calendar date instead of UTC (#510). Optional for hand-built test
    # compositions; real composition always sets it.
    get_academy_timezone: object = None
    # Attendance correction (#517)
    correct_attendance: CorrectAttendance | None = None
    # Session announcements (#614) — SessionAnnouncementService
    session_announcements: object = None
    # Coach supervision (#632): academy-wide upcoming list and coach-name
    # resolution for admins/owners covering the coach surface.
    list_all_sessions_for_academy: object = None  # Callable[[], Awaitable[list[...]]]
    resolve_user_names: object = None  # Callable[[Sequence[str]], Awaitable[dict[str, str]]]
    # Note visibility (coach phone slice 3). Optional defaults keep hand-built
    # test compositions working; real composition always sets both.
    set_progress_note_visibility: SetProgressNoteVisibility | None = None
    set_skill_note_visibility: SetSkillNoteVisibility | None = None


class CoachAssignedSessionLookup:
    """Answers "may this user act as the coach of this session?".

    The single choke point for every assignment check on the coach surface
    (roster, notes, feedback, announcements, skills, teaching plan). An
    assistant coach listed in the session's ``assistant_coach_ids`` counts as
    assigned to that session (and only that session). A coach
    supervisor — an academy admin/owner covering any session (#632) — passes
    for every session *in this tenant*: the tenant-scoped session lookup
    runs first, so a supervisor still cannot reach another academy's
    session. ``is_supervisor`` is consulted only after the direct
    assignment test fails, so the ordinary coach path costs nothing extra.
    """

    def __init__(
        self,
        sessions: MongoSessionRepository,
        *,
        is_supervisor: Callable[[str], Awaitable[bool]] | None = None,
    ) -> None:
        self._sessions = sessions
        self._is_supervisor = is_supervisor

    async def is_coach_assigned(self, coach_id: str, session_id: str) -> bool:
        session = await self._sessions.get(session_id)
        if session is None:
            return False
        if session.coach_id == coach_id or coach_id in session.assistant_coach_ids:
            return True
        if self._is_supervisor is None:
            return False
        return await self._is_supervisor(coach_id)


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
    membership_repo = MongoMembershipRepository(db)

    async def is_coach_supervisor_user(user_id: str) -> bool:
        """Does ``user_id`` hold a supervisor role in the request's academy?

        Re-derives the answer from the same ``academy_memberships`` row
        ``load_auth_claims`` built ``claims.roles`` from (alias-matched the
        same way), so the coach surface and the auth layer can never
        disagree about who is an admin here. Tenant comes from the request
        context at call time, never from composition.
        """
        academy_id = request_academy_id()
        user = await user_repo.get_by_id(user_id)
        aliases = identity_aliases(user.user_id, user.firebase_uid, user.auth_uid) if user else ()
        membership = await membership_repo.get_membership(academy_id, user_id, aliases=aliases)
        if membership is None or not membership.is_active():
            return False
        return any(role in membership.roles for role in COACH_SUPERVISOR_ROLES)

    assigned_sessions = CoachAssignedSessionLookup(
        sessions_repo, is_supervisor=is_coach_supervisor_user
    )
    absence_notice_repo = MongoAbsenceNoticeRepository(db)
    occurrence_roster_repo = MongoOccurrenceRosterRepository(db)
    # Billing repos for session-type move surface
    session_type_repo = MongoSessionTypeRepository(db)
    billing_enrollment_repo = MongoStudentBillingEnrollmentRepository(db)
    # Skill note repo
    skill_note_repo = MongoSkillNoteRepository(db)
    # Messages inbox (UIM13) — shared comms store, per-recipient read routes.
    messages_repo = MongoMessageRepository(db)

    async def _visible_session_ids(coach_id: str) -> list[str]:
        """Sessions assigned to this coach (#614).

        Mirrors ``CoachAssignedSessionLookup``: assignment is the session's
        primary ``coach_id``, with no date window. ``for_coach`` is the wrong
        source here — it filters ``start_at >= now``, and a recurring series
        keeps the single ``start_at`` stamped when it was created, so a class
        that has been running for months would drop out of the coach's inbox
        while the route still lets that same coach *post* to it. A replacement
        coach covering one occurrence is still not an audience, consistent
        with every other coach session route. Neither is an assistant coach:
        the sessions that merely list the user in ``assistant_coach_ids`` are
        excluded (``include_assistant=False``) — assistants never message or
        receive messages from families.

        Read at execution time; the tenant comes from ``current_academy_id()``
        inside the closure, never from a composition-time capture.
        """
        return await sessions_repo.assigned_session_ids_for_coach(coach_id, include_assistant=False)

    async def list_messages(coach_id: str) -> list[Message]:
        return await messages_repo.for_recipient(
            coach_id, visible_session_ids=await _visible_session_ids(coach_id)
        )

    async def mark_message_read(message_id: str, user_id: str) -> None:
        await messages_repo.mark_read(
            message_id, user_id, visible_session_ids=await _visible_session_ids(user_id)
        )

    async def resolve_user_names(user_ids: Sequence[str]) -> dict[str, str]:
        """Display names for a handful of coach ids (supervisor list labels)."""
        unique = sorted({uid for uid in user_ids if uid})
        users = await asyncio.gather(*(user_repo.get_by_id(uid) for uid in unique))
        return {uid: user.display_name for uid, user in zip(unique, users, strict=True) if user}

    def request_academy_id() -> str:
        try:
            return current_academy_id()
        except TenantContextUnset:
            # Fail closed in multi-academy mode: reaching here without tenant
            # context is always a bug there. The boot fallback only exists so
            # single-academy non-HTTP callers behave exactly as today.
            if settings.tenancy_mode == "multi_academy":
                raise
            return settings.primary_academy_id or settings.default_academy_id

    async def get_dashboard_metrics(coach_id: str) -> dict[str, int | float]:
        academy_id = request_academy_id()
        today = datetime.now(UTC).date()
        today_sessions = await sessions_repo.for_coach_on_date(coach_id, today)
        session_cursor = sessions_repo._find_many({"coach_id": coach_id, "status": "scheduled"})
        session_ids = [str(doc["session_id"]) async for doc in session_cursor]
        student_ids = (
            await enrollments_repo.collection.distinct(
                "student_id",
                {
                    "academy_id": academy_id,
                    "session_id": {"$in": session_ids},
                    "status": "active",
                },
            )
            if session_ids
            else []
        )
        total_marks = await attendance_repo.collection.count_documents(
            {"academy_id": academy_id, "marked_by": coach_id}
        )
        present_marks = await attendance_repo.collection.count_documents(
            {
                "academy_id": academy_id,
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
            email=body.email,
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

    student_progress_comp = compose_student_progress(
        db, outbox, idempotency_store=idempotency_store
    )
    generate_daily_teaching_plan = GenerateDailyTeachingPlan(
        occurrences=ListCoachOccurrencesForDate(
            occurrences=occurrences_repo, sessions=sessions_repo
        ),
        get_roster=GetSessionRoster(enrollments=enrollments_repo, students=students_repo),
        teaching_focus=student_progress_comp.get_teaching_focus,
        lesson_cards=MongoLessonCardRepository(db),
        video_refs=MongoCurriculumVideoRefRepository(db),
        criteria=MongoCriterionRepository(db),
    )

    get_roster = GetSessionRoster(enrollments=enrollments_repo, students=students_repo)

    return CoachComposition(
        list_today=ListCoachOccurrencesForDate(
            occurrences=occurrences_repo, sessions=sessions_repo
        ),
        get_roster=get_roster,
        get_occurrence_roster=GetOccurrenceRoster(
            get_roster=get_roster,
            absence_notices=absence_notice_repo,
            occurrence_roster=occurrence_roster_repo,
            students=students_repo,
        ),
        mark_attendance=MarkAttendance(
            attendance_repo=attendance_repo,
            occurrence_lookup=EnrollmentOccurrenceLookup(occurrences_repo),
            enrollment_lookup=EnrollmentLookupAdapter(enrollments_repo),
            outbox=outbox,
            idempotency_store=idempotency_store,
            academy_id=request_academy_id,
        ),
        correct_attendance=CorrectAttendance(
            attendance_repo=attendance_repo,
            occurrence_lookup=EnrollmentOccurrenceLookup(occurrences_repo),
            outbox=outbox,
            academy_id=request_academy_id,
        ),
        bulk_mark_attendance=BulkMarkAttendance(
            attendance_repo=attendance_repo,
            occurrence_lookup=EnrollmentOccurrenceLookup(occurrences_repo),
            enrollment_lookup=EnrollmentLookupAdapter(enrollments_repo),
            outbox=outbox,
            idempotency_store=idempotency_store,
            academy_id=request_academy_id,
        ),
        list_attendance_for_occurrence=attendance_repo.list_for_occurrence,
        get_dashboard_metrics=get_dashboard_metrics,
        create_lesson_plan=CreateLessonPlan(notes=notes_repo, sessions=assigned_sessions),
        list_lesson_plans=ListLessonPlans(notes=notes_repo, sessions=assigned_sessions),
        create_progress_note=CreateProgressNote(
            notes=notes_repo,
            sessions=assigned_sessions,
            enrollments=enrollments_repo,
        ),
        list_progress_notes=ListProgressNotes(notes=notes_repo, sessions=assigned_sessions),
        set_progress_note_visibility=SetProgressNoteVisibility(
            notes=notes_repo, sessions=assigned_sessions
        ),
        assigned_sessions=assigned_sessions,
        add_student_to_roster=CoachAddStudentToRoster(
            sessions=sessions_repo,
            enrollments=enrollments_repo,
            students=students_repo,
            assigned_sessions=assigned_sessions,
            academy_id=request_academy_id,
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
        # issue #651: paused students stay on the roster, so coach
        # authorisation reads active-or-paused, not active only.
        get_active_session_enrollments_for_student=enrollments_repo.active_or_paused_for_student,
        list_all_sessions=ListCoachUpcomingOccurrences(
            occurrences=occurrences_repo,
            sessions=sessions_repo,
        ).execute,
        list_all_sessions_for_academy=ListCoachUpcomingOccurrences(
            occurrences=occurrences_repo,
            sessions=sessions_repo,
        ).execute_for_academy,
        resolve_user_names=resolve_user_names,
        get_profile=get_profile,
        update_profile=update_profile,
        # Skill pathway
        create_skill_note=CreateSkillNote(notes=skill_note_repo),
        list_skill_notes=ListSkillNotes(notes=skill_note_repo),
        set_skill_note_visibility=SetSkillNoteVisibility(notes=skill_note_repo),
        student_progress=student_progress_comp,
        curriculum=compose_curriculum(db),
        generate_daily_teaching_plan=generate_daily_teaching_plan,
        list_messages=list_messages,
        mark_message_read=mark_message_read,
        session_announcements=compose_announcements(
            db,
            settings,
            # Same construction as admin.py. `academy_id` here only labels the
            # returned domain object; every write is scoped by the tenant-aware
            # repository, and `post_session_announcement` reads the live tenant.
            comms=CommsService(
                messages=messages_repo,
                academy_id=settings.primary_academy_id or settings.default_academy_id,
            ),
            users=user_repo,
            sessions=sessions_repo,
        ),
        get_academy_timezone=academy_timezone_lookup(db),
    )
