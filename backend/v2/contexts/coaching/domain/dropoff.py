"""Parent drop-off check-in: the parent reports "I've arrived" for one dated
class, staff confirm they have the child, and the confirmation writes the
official attendance mark through ``MarkAttendance``.

A check-in is never attendance by itself, and the state callers show is
derived from the attendance mark, not from the stored status: ``confirmed``
means a non-voided present/late mark exists for that (occurrence, student),
however it was written (this confirm, a manual tap or "Mark all present").
A later void, or an Absent mark, therefore never reads as "Checked in".
``expired`` is never stored: a report with no present mark after the window
closes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel

#: Stored lifecycle. ``confirming`` is the in-flight step between claiming
#: the report and writing the mark, so a crash in between can be retried.
DropoffCheckinStatus = Literal["reported", "confirming", "confirmed"]
#: What callers show. ``pending`` covers reported and confirming.
DropoffCheckinState = Literal["none", "pending", "confirmed", "expired"]


class DropoffCheckin(BaseModel):
    """One parent arrival report for one student on one occurrence."""

    model_config = {"frozen": True}

    checkin_id: str
    academy_id: str
    occurrence_id: str
    session_id: str
    student_id: str
    reported_by: str  # parent user_id
    reported_at: datetime  # server clock
    status: DropoffCheckinStatus = "reported"
    confirm_mutation_id: str | None = None
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None
    attendance_id: str | None = None
    #: True when a present/late mark already existed, so the confirmation
    #: linked to it instead of writing a second one.
    reconciled_with_existing_mark: bool = False


def confirm_mutation_id_for(checkin_id: str) -> str:
    """Deterministic, so two staff confirming at once write one mark."""
    return f"dropoff:{checkin_id}"


class DropoffWindow(BaseModel):
    model_config = {"frozen": True}

    opens_at: datetime
    closes_at: datetime

    def contains(self, now: datetime) -> bool:
        return self.opens_at <= now <= self.closes_at


def dropoff_window(
    starts_at: datetime, *, opens_minutes_before: int, closes_minutes_after: int
) -> DropoffWindow:
    """Window around the occurrence's CURRENT start, so a reschedule moves it.

    Instants are compared in UTC; the academy timezone only changes how the
    times are displayed, never where the window falls.
    """
    if starts_at.tzinfo is None:
        starts_at = starts_at.replace(tzinfo=UTC)
    return DropoffWindow(
        opens_at=starts_at - timedelta(minutes=opens_minutes_before),
        closes_at=starts_at + timedelta(minutes=closes_minutes_after),
    )


#: Attendance statuses that mean the child was there.
PRESENT_STATUSES = frozenset({"present", "late"})


def checkin_state(
    row: DropoffCheckin | None, window: DropoffWindow, now: datetime, *, marked_present: bool
) -> DropoffCheckinState:
    """``marked_present``: a non-voided present/late mark exists."""
    if row is None:
        return "none"
    if marked_present:
        return "confirmed"
    # A ``confirming`` row past the window still finishes on a staff retry
    # (ConfirmDropoff does not re-check the window for it); it just stops
    # reading as pending, so nothing hangs on "Waiting for staff" forever.
    if now > window.closes_at:
        return "expired"
    return "pending"
