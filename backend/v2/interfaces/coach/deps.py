"""Coach BFF dependency providers.

Reads composed use cases from ``request.app.state.coach`` (wired by the
composition root in main.py). Routes depend on these helpers so they
never touch infrastructure directly.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from fastapi import Request

from backend.v2.composition.pathway import CurriculumComposition, StudentProgressComposition
from backend.v2.contexts.billing.application.use_cases.session_type_ops import (
    ListSessionTypes,
    ListStudentBillingEnrollments,
    MoveStudentSessionType,
    PreviewStudentSessionTypeMove,
)
from backend.v2.contexts.coaching.application.use_cases.bulk_mark_attendance import (
    BulkMarkAttendance,
)
from backend.v2.contexts.coaching.application.use_cases.correct_attendance import (
    CorrectAttendance,
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
    SetSkillNoteVisibility,
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
)
from backend.v2.shared.comms import Message


@dataclass
class CoachUseCases:
    list_today: ListCoachOccurrencesForDate
    get_roster: GetSessionRoster
    mark_attendance: MarkAttendance
    bulk_mark_attendance: BulkMarkAttendance
    get_dashboard_metrics: object  # callable
    create_lesson_plan: CreateLessonPlan
    list_lesson_plans: ListLessonPlans
    create_progress_note: CreateProgressNote
    list_progress_notes: ListProgressNotes
    assigned_sessions: object  # CoachAssignedSessionLookup (any with is_coach_assigned)
    add_student_to_roster: CoachAddStudentToRoster
    remove_student_from_roster: CoachRemoveStudentFromRoster
    create_feedback: CreateSessionFeedback
    list_feedback: ListSessionFeedback
    # Phase 2 — billing enrollment move surface
    list_billing_enrollments: ListStudentBillingEnrollments
    preview_student_session_type_move: PreviewStudentSessionTypeMove
    move_student_session_type: MoveStudentSessionType
    list_session_types: ListSessionTypes
    get_billing_enrollment: Callable[[str], Awaitable[Any | None]]
    get_active_session_enrollments_for_student: Callable[[str], Awaitable[list[Any]]]
    list_all_sessions: object  # Callable[[str], Awaitable[list[Session]]]
    get_profile: object  # Callable[[str], Awaitable[CoachProfileResponse | None]]
    update_profile: (
        object  # Callable[[str, body, academy_id], Awaitable[CoachProfileResponse | None]]
    )
    # Skill pathway surface. Optional so existing CoachUseCases constructions
    # (and the shared coach test fixtures) that predate the skill pathway keep
    # working. Real coach composition always sets these; only the skill routes
    # consume them.
    student_progress: StudentProgressComposition | None = None
    curriculum: CurriculumComposition | None = None
    create_skill_note: object | None = None  # CreateSkillNote
    list_skill_notes: object | None = None  # ListSkillNotes
    # Coach daily teaching plan (lesson guidance). Optional for backward compat
    # with test fixtures that predate it; real coach composition always sets it.
    generate_daily_teaching_plan: object | None = None  # GenerateDailyTeachingPlan
    # Callable[[str], Awaitable[list[Attendance]]] — existing student marks for
    # one occurrence so /coach/today can hydrate attendance state on reload.
    # Optional for fixtures that predate it; real composition always sets it.
    list_attendance_for_occurrence: object | None = None
    # Occurrence-scoped roster (expected-absence flags + one-time makeup/
    # trial entries) for /coach/today. Optional for fixtures that predate
    # it; real composition always sets it. today_routes.py falls back to
    # `get_roster` (plain, session-scoped) when this is None.
    get_occurrence_roster: GetOccurrenceRoster | None = None
    # Messages inbox (UIM13). Optional for backward compat with fixtures that
    # predate it; real coach composition always sets both.
    list_messages: Callable[[str], Awaitable[list[Message]]] | None = None
    mark_message_read: Callable[[str, str], Awaitable[None]] | None = None
    # IANA timezone name for an academy so /coach/today can default "today"
    # to the academy-local calendar date instead of UTC (#510). Optional for
    # fixtures that predate it; real composition always sets it.
    get_academy_timezone: Callable[[str], Awaitable[str | None]] | None = None
    # Attendance correction (#517). Optional for fixtures that predate it;
    # real coach composition always sets it.
    correct_attendance: CorrectAttendance | None = None
    # Session announcements (#614) — SessionAnnouncementService. Typed loosely
    # so this module keeps importing only what routes need; the announcement
    # routes hold the concrete type.
    session_announcements: object | None = None
    # Coach supervision (#632). ``list_all_sessions_for_academy`` mirrors
    # ``list_all_sessions`` without the coach filter; ``resolve_user_names``
    # maps user ids to display names so an admin's academy-wide list can
    # label each session with its coach. Both optional for fixtures that
    # predate them; real coach composition always sets them. When
    # ``list_all_sessions_for_academy`` is None a supervisor falls back to
    # the coach-scoped list.
    list_all_sessions_for_academy: Callable[[], Awaitable[list[Any]]] | None = None
    resolve_user_names: Callable[[Sequence[str]], Awaitable[dict[str, str]]] | None = None
    # Note visibility (coach phone slice 3): share a note with the parent or
    # make it private again. The progress-note one is required by its route
    # but optional here so fixtures that predate it keep constructing; the
    # skill-note one is optional like ``create_skill_note`` (503 when unset).
    set_progress_note_visibility: SetProgressNoteVisibility | None = None
    set_skill_note_visibility: SetSkillNoteVisibility | None = None


def get_coach_use_cases(request: Request) -> CoachUseCases:
    return request.app.state.coach  # type: ignore[no-any-return]


async def coach_names_for(
    sessions: Sequence[Any],
    *,
    use_cases: CoachUseCases,
    supervisor: bool,
) -> dict[str, str]:
    """Coach display names keyed by coach id — coach supervisors only (#632).

    Coaches looking at their own list already know who they are, so the
    lookup is skipped on that path and ``coach_name`` stays null.
    """
    resolve = getattr(use_cases, "resolve_user_names", None)
    if not supervisor or resolve is None:
        return {}
    coach_ids = [cid for cid in (getattr(s, "coach_id", None) for s in sessions) if cid]
    if not coach_ids:
        return {}
    names: dict[str, str] = await resolve(coach_ids)
    return names
