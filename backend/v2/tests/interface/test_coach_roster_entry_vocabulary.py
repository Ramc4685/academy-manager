"""Issue #773 / #732: the coach roster's status Literal must admit every
status ``GetSessionRoster`` can hand it.

The #732 failure mode is not a bad row rendering oddly — it is FastAPI
rejecting the whole response, so one student mid-seat-reclaim blanks the
coach's entire day. ``reclaim_pending`` is NON_TERMINAL and roster-visible,
so it reaches this model; the Literal simply did not list it.
"""

from __future__ import annotations

from datetime import date

from backend.v2.contexts.enrollment.domain.models import NON_TERMINAL
from backend.v2.interfaces.coach.views import CoachRosterEntry


def test_reclaim_pending_validates_on_the_coach_roster() -> None:
    entry = CoachRosterEntry(
        student_id="st-1", full_name="Alice", enrollment_status="reclaim_pending"
    )
    assert entry.enrollment_status == "reclaim_pending"


def test_every_non_terminal_status_validates_on_the_coach_roster() -> None:
    for status in sorted(NON_TERMINAL):
        entry = CoachRosterEntry(
            student_id="st-1",
            full_name="Alice",
            enrollment_status=status,  # type: ignore[arg-type]
        )
        assert entry.enrollment_status == status


def test_a_held_row_carries_its_return_date_to_the_coach() -> None:
    """#773: the roster already knew the row was held; it never said until when."""
    entry = CoachRosterEntry(
        student_id="st-1",
        full_name="Alice",
        enrollment_status="held",
        hold_return_on=date(2026, 10, 15),
    )
    assert entry.hold_return_on == date(2026, 10, 15)
