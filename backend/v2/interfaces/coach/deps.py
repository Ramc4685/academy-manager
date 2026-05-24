"""Coach BFF dependency providers.

Reads composed use cases from ``request.app.state.coach`` (wired by the
composition root in main.py). Routes depend on these helpers so they
never touch infrastructure directly.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from backend.v2.contexts.coaching.application.use_cases.mark_attendance import MarkAttendance
from backend.v2.contexts.coaching.application.use_cases.session_notes import (
    CreateLessonPlan,
    CreateProgressNote,
    ListLessonPlans,
    ListProgressNotes,
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
    get_dashboard_metrics: object  # callable
    create_lesson_plan: CreateLessonPlan
    list_lesson_plans: ListLessonPlans
    create_progress_note: CreateProgressNote
    list_progress_notes: ListProgressNotes


def get_coach_use_cases(request: Request) -> CoachUseCases:
    return request.app.state.coach  # type: ignore[no-any-return]
