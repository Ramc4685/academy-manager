"""Coach BFF dependency providers.

Reads composed use cases from ``request.app.state.coach`` (wired by the
composition root in main.py). Routes depend on these helpers so they
never touch infrastructure directly.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from backend.v2.contexts.coaching.application.use_cases.mark_attendance import MarkAttendance
from backend.v2.contexts.enrollment.application.use_cases.get_session_roster import (
    GetSessionRoster,
)
from backend.v2.contexts.enrollment.application.use_cases.list_coach_sessions_for_date import (
    ListCoachSessionsForDate,
)


@dataclass
class CoachUseCases:
    list_today: ListCoachSessionsForDate
    get_roster: GetSessionRoster
    mark_attendance: MarkAttendance


def get_coach_use_cases(request: Request) -> CoachUseCases:
    return request.app.state.coach  # type: ignore[no-any-return]
