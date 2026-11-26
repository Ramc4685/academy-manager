"""The one definition of held class, headcount and attendance the reports share."""

from __future__ import annotations

from datetime import UTC, datetime

from backend.v2.shared.reporting_definitions import (
    Headcount,
    attendance_for_classes_filter,
    class_state,
    headcount,
    is_held,
    is_present,
)

NOW = datetime(2026, 11, 26, 12, tzinfo=UTC)


def test_a_class_is_held_by_status_or_by_the_clock() -> None:
    assert class_state({"status": "completed", "end_at": datetime(2999, 1, 1)}, now=NOW) == "held"
    assert class_state({"status": "scheduled", "end_at": datetime(2026, 11, 1, 10)}, now=NOW) == (
        "held"
    )
    assert class_state({"status": "scheduled", "end_at": datetime(2026, 11, 30)}, now=NOW) == (
        "upcoming"
    )
    assert class_state({"status": "scheduled"}, now=NOW) == "upcoming"


def test_a_cancelled_class_is_never_held_even_after_it_ends() -> None:
    occurrence = {"status": "cancelled", "end_at": datetime(2026, 11, 1, tzinfo=UTC)}
    assert class_state(occurrence, now=NOW) == "cancelled"
    assert not is_held(occurrence, now=NOW)


def test_headcount_separates_enrolled_from_paying() -> None:
    enrollments = [{} for _ in range(9)] + [
        {"billing_type": "NoCharge"},
        {"billing_type": "waived"},
    ]
    count = headcount(enrollments)
    assert count == Headcount(enrolled=11, paying=9)
    assert count.not_billed == 2


def test_attendance_is_matched_by_class_not_by_when_it_was_marked() -> None:
    query = attendance_for_classes_filter(["occ-b", "occ-a", "occ-a"])
    assert query == {
        "occurrence_id": {"$in": ["occ-a", "occ-b"]},
        "status": {"$in": ["present", "late", "absent"]},
    }
    assert "marked_at" not in query
    assert is_present("late") and not is_present("absent") and not is_present("voided")
