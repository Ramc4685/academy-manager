from __future__ import annotations

import pytest
from pydantic import BaseModel


class EnrollmentEventDto(BaseModel):
    event_id: str
    event_type: str
    effective_date: str
    actor_id: str
    reason: str | None = None
    billing_result: str | None = None
    credit_reference: str | None = None


class EnrollmentEventsResponse(BaseModel):
    enrollment_id: str
    events: list[EnrollmentEventDto]


def test_enrollment_event_dto_event_type_field():
    e = EnrollmentEventDto(
        event_id="e1",
        event_type="paused",
        effective_date="2026-05-22",
        actor_id="admin1",
    )
    assert e.event_type == "paused"
    assert e.reason is None


def test_enrollment_events_response_shape():
    r = EnrollmentEventsResponse(enrollment_id="enr1", events=[])
    assert r.enrollment_id == "enr1"
    assert r.events == []
