"""A reported absence's makeup state comes from the existing makeup rules.

``DescribeAbsenceMakeups`` reads an existing request first (booked, requested,
expired), then runs the same ``MakeupEligibility`` check as
``SubmitMakeupRequest`` (eligible, expired, reported). No new rules.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from backend.v2.contexts.enrollment.application.use_cases.makeup_requests import (
    DescribeAbsenceMakeups,
)
from backend.v2.contexts.enrollment.domain.self_service import (
    MakeupRequest,
    ParentSelfServicePolicy,
)
from backend.v2.tests.application.test_makeup_candidates import _Enrollments, _Presence
from backend.v2.tests.application.test_makeup_requests import (
    _absence_notice,
    _enrollment,
    _FakeMakeups,
    _FakeNotices,
    _FakeOccurrences,
    _FakePolicies,
    _now,
    _occurrence,
)

NOW = _now()
KEY = ("student-1", "occ-missed")


def _use_case(*, occurrence, makeups=None, policy=None, window_met=True, present=()):
    return DescribeAbsenceMakeups(
        occurrences=_FakeOccurrences([occurrence]),
        enrollments=_Enrollments([_enrollment()]),
        notices=_FakeNotices([_absence_notice(window_met=window_met)]),
        makeups=makeups or _FakeMakeups(),
        policies=_FakePolicies(policy),
        attendance=_Presence(present),
        clock=_now,
    )


def _request(status: str, **kw) -> MakeupRequest:
    return MakeupRequest(
        request_id="mr-1",
        academy_id="acad",
        student_id="student-1",
        parent_id="parent-1",
        missed_occurrence_id="occ-missed",
        status=status,  # type: ignore[arg-type]
        expires_at=NOW + timedelta(days=20),
        created_at=NOW - timedelta(days=1),
        **kw,
    )


def _makeups(*requests: MakeupRequest) -> _FakeMakeups:
    fake = _FakeMakeups()
    fake.added.extend(requests)
    return fake


@pytest.mark.asyncio
async def test_upcoming_class_is_reported() -> None:
    result = await _use_case(occurrence=_occurrence(start_at=NOW + timedelta(days=2))).execute(
        [KEY]
    )

    assert result[KEY].state == "reported"
    assert result[KEY].reason is None


@pytest.mark.asyncio
async def test_missed_class_inside_the_window_is_eligible_with_its_expiry() -> None:
    missed_at = NOW - timedelta(days=2)
    result = await _use_case(occurrence=_occurrence(start_at=missed_at)).execute([KEY])

    assert result[KEY].state == "eligible"
    assert result[KEY].expires_at == missed_at + timedelta(days=30)


@pytest.mark.asyncio
async def test_approved_request_is_booked_onto_its_target_class() -> None:
    result = await _use_case(
        occurrence=_occurrence(start_at=NOW - timedelta(days=2)),
        makeups=_makeups(_request("approved", approved_target_occurrence_id="occ-target")),
    ).execute([KEY])

    assert result[KEY].state == "booked"
    assert result[KEY].booked_occurrence_id == "occ-target"


@pytest.mark.asyncio
async def test_booked_stays_booked_after_the_request_window_passes() -> None:
    result = await _use_case(
        occurrence=_occurrence(start_at=NOW - timedelta(days=60)),
        makeups=_makeups(_request("completed", approved_target_occurrence_id="occ-target")),
    ).execute([KEY])

    assert result[KEY].state == "booked"


@pytest.mark.asyncio
async def test_missed_class_past_the_window_is_expired() -> None:
    result = await _use_case(occurrence=_occurrence(start_at=NOW - timedelta(days=31))).execute(
        [KEY]
    )

    assert result[KEY].state == "expired"


@pytest.mark.asyncio
async def test_lapsed_request_is_expired() -> None:
    result = await _use_case(
        occurrence=_occurrence(start_at=NOW - timedelta(days=2)),
        makeups=_makeups(_request("expired")),
    ).execute([KEY])

    assert result[KEY].state == "expired"


@pytest.mark.asyncio
async def test_pending_request_is_requested_not_offered_again() -> None:
    result = await _use_case(
        occurrence=_occurrence(start_at=NOW - timedelta(days=2)),
        makeups=_makeups(_request("pending")),
    ).execute([KEY])

    assert result[KEY].state == "requested"
    assert result[KEY].expires_at == NOW + timedelta(days=20)


@pytest.mark.asyncio
async def test_denied_request_falls_back_to_the_eligibility_check() -> None:
    result = await _use_case(
        occurrence=_occurrence(start_at=NOW - timedelta(days=2)),
        makeups=_makeups(_request("denied", denial_reason="no")),
    ).execute([KEY])

    assert result[KEY].state == "eligible"


@pytest.mark.asyncio
async def test_late_notice_is_reported_with_the_reason_when_notice_is_required() -> None:
    result = await _use_case(
        occurrence=_occurrence(start_at=NOW - timedelta(days=2)), window_met=False
    ).execute([KEY])

    assert result[KEY].state == "reported"
    assert result[KEY].reason is not None and "notice window" in result[KEY].reason


@pytest.mark.asyncio
async def test_marked_present_is_reported_not_eligible() -> None:
    result = await _use_case(
        occurrence=_occurrence(start_at=NOW - timedelta(days=2)), present=[KEY[::-1]]
    ).execute([KEY])

    assert result[KEY].state == "reported"
    assert result[KEY].reason == "Marked present for this class."


@pytest.mark.asyncio
async def test_makeups_turned_off_reports_every_absence() -> None:
    policy = ParentSelfServicePolicy.default("acad").model_copy(
        update={"can_request_makeup": False}
    )
    result = await _use_case(
        occurrence=_occurrence(start_at=NOW - timedelta(days=2)), policy=policy
    ).execute([KEY])

    assert result[KEY].state == "reported"
