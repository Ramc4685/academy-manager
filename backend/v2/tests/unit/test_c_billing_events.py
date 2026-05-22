from __future__ import annotations

from backend.v2.interfaces.admin.views import EnrollmentEventDto, EnrollmentEventsResponse
from backend.v2.interfaces.admin.views import GenerateMonthlyPaymentsRequest


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


def test_generate_monthly_accepts_month_alias():
    req = GenerateMonthlyPaymentsRequest.model_validate({"month": "2026-05"})
    assert req.period == "2026-05"


def test_generate_monthly_period_canonical():
    req = GenerateMonthlyPaymentsRequest.model_validate({"period": "2026-05"})
    assert req.period == "2026-05"


def test_generate_monthly_raises_without_either():
    import pytest
    with pytest.raises(Exception):
        GenerateMonthlyPaymentsRequest.model_validate({})
