"""Coach BFF dependency providers.

Reads composed use cases from ``request.app.state.coach`` (wired by the
composition root in main.py). Routes depend on these helpers so they
never touch infrastructure directly.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi import Request

from backend.v2.composition.pathway import StudentProgressComposition
from backend.v2.contexts.billing.application.use_cases.session_type_ops import (
    ListSessionTypes,
    ListStudentBillingEnrollments,
    MoveStudentSessionType,
    PreviewStudentSessionTypeMove,
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
    create_skill_note: object | None = None  # CreateSkillNote
    list_skill_notes: object | None = None  # ListSkillNotes


def get_coach_use_cases(request: Request) -> CoachUseCases:
    return request.app.state.coach  # type: ignore[no-any-return]
