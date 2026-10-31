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


def test_roster_row_carries_one_payment_due_amount_when_overdue(coach_client):
    """Issue #774: the only money fact a coach sees, in integer cents."""
    coach_client.overdue_cents["st1"] = 7000

    r = coach_client.get("/api/v2/coach/today?date=2026-05-16")

    assert r.status_code == 200, r.text
    roster = r.json()["sessions"][0]["roster"]
    by_student = {row["student_id"]: row["payment_due_cents"] for row in roster}
    assert by_student["st1"] == 7000
    # A student who owes nothing carries no chip at all — not a zero.
    assert by_student["st2"] is None


def test_coach_persona_no_longer_mounts_any_billing_route(coach_client):
    """Owner decision 2026-09-12: coaches see the chip and nothing else."""
    paths = {getattr(route, "path", "") for route in coach_client.app.routes}
    assert not [path for path in paths if "billing" in path]
