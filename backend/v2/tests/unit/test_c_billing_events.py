from __future__ import annotations

from backend.v2.interfaces.admin.views import EnrollmentEventDto, EnrollmentEventsResponse


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
