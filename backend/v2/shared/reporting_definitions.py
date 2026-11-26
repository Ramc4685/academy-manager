"""One definition each for what the admin reports count.

Month close, the reports dashboard, session economics, attendance trends and
coach utilisation all answer the same three questions. They used to answer
them differently (a class "completed" by a status nothing writes, attendance
bucketed by when it was marked, headcounts with and without not-billed
children), so the same month read 0 completed next to an 82% attendance rate.

- **Held class**: a ``session_occurrences`` row that is not cancelled and is
  completed by status or by the clock (its end time has passed).
- **Enrolled vs paying**: enrolled is every active enrollment; paying leaves
  out the not-billed ones (:func:`backend.v2.shared.billing_type.is_not_billed`).
- **Attendance by class date**: a mark counts in the month its class met
  (its occurrence's ``start_at``), not the month it was marked.
- **Month**: ``[first instant, next month's first instant)`` on the
  academy's own clock (:func:`month_window`).

Lives in ``shared`` because billing and finance both read it and contexts may
not import one another.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Literal
from zoneinfo import ZoneInfo

from backend.v2.shared.billing_type import is_not_billed

#: Attendance-rate denominator and numerator (#554). ``voided`` appears in
#: neither: an annulled mark drops out of the rate rather than counting as an
#: absence.
ATTENDANCE_COUNTED_STATUSES: Final[tuple[str, ...]] = ("present", "late", "absent")
ATTENDANCE_PRESENT_STATUSES: Final[frozenset[str]] = frozenset({"present", "late"})

ClassState = Literal["held", "upcoming", "cancelled"]


def as_utc(value: object) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def report_zone(timezone_name: str | None) -> ZoneInfo:
    """The academy's reporting zone, falling back to UTC on an unknown name.

    Reads must render something: a nonsense ``academies.timezone`` degrades to
    the pre-#608 UTC behaviour rather than 500-ing a report.
    """
    if not timezone_name:
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(timezone_name)
    except (KeyError, ValueError):
        return ZoneInfo("UTC")


def month_window(period: str, timezone_name: str | None = None) -> tuple[datetime, datetime]:
    """UTC bounds of ``YYYY-MM`` as the academy's clock sees it (#608)."""
    year, month = (int(part) for part in period.split("-", 1))
    zone = report_zone(timezone_name)
    start = datetime(year, month, 1, tzinfo=zone)
    end = (
        datetime(year + 1, 1, 1, tzinfo=zone)
        if month == 12
        else datetime(year, month + 1, 1, tzinfo=zone)
    )
    return start.astimezone(UTC), end.astimezone(UTC)


def class_state(occurrence: Mapping[str, Any], *, now: datetime) -> ClassState:
    """Held, upcoming or cancelled, for one ``session_occurrences`` row."""
    status = str(occurrence.get("status") or "scheduled")
    if status == "cancelled":
        return "cancelled"
    if status == "completed":
        return "held"
    end_at = as_utc(occurrence.get("end_at"))
    return "held" if end_at is not None and end_at < now else "upcoming"


@dataclass(frozen=True)
class Headcount:
    enrolled: int
    paying: int


def headcount(active_enrollments: Iterable[Mapping[str, Any]]) -> Headcount:
    """Enrolled and paying, over enrollments already filtered to active."""
    enrolled = paying = 0
    for enrollment in active_enrollments:
        enrolled += 1
        if not is_not_billed(enrollment):
            paying += 1
    return Headcount(enrolled=enrolled, paying=paying)


def attendance_for_classes_filter(occurrence_ids: Iterable[str]) -> dict[str, Any]:
    """The ``attendance`` match for marks on these classes (attendance by
    class date: pass the ids of the month's classes)."""
    return {
        "occurrence_id": {"$in": sorted(set(occurrence_ids))},
        "status": {"$in": list(ATTENDANCE_COUNTED_STATUSES)},
    }


def is_present(attendance_status: object) -> bool:
    return str(attendance_status) in ATTENDANCE_PRESENT_STATUSES
