"""Pure domain tests for Enrollment models."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from backend.v2.contexts.enrollment.domain.models import (
    Enrollment,
    RosterEntry,
    Session,
    Student,
)


def _session() -> Session:
    return Session(
        session_id="s1",
        academy_id="acad",
        coach_id="c1",
        title="Junior A",
        location="Court 1",
        start_at=datetime(2026, 5, 16, 9, 0, tzinfo=timezone.utc),
        end_at=datetime(2026, 5, 16, 10, 30, tzinfo=timezone.utc),
        capacity=8,
    )


def test_session_capacity_must_be_positive() -> None:
    # model_copy(update=...) skips validation by default; construct a fresh
    # Session to force re-validation of the `capacity >= 1` invariant.
    base = _session().model_dump()
    base["capacity"] = 0
    with pytest.raises(ValidationError):
        Session(**base)


def test_session_frozen() -> None:
    s = _session()
    with pytest.raises(ValidationError):
        s.coach_id = "c2"  # type: ignore[misc]


def test_roster_entry_carries_status_from_enrollment() -> None:
    e = Enrollment(
        enrollment_id="e1",
        academy_id="acad",
        session_id="s1",
        student_id="st1",
        status="active",
    )
    s = Student(student_id="st1", academy_id="acad", parent_id="p1", full_name="Alice")
    re = RosterEntry(
        enrollment_id=e.enrollment_id,
        student_id=s.student_id,
        full_name=s.full_name,
        status=e.status,
    )
    assert re.status == "active"
    assert re.full_name == "Alice"
