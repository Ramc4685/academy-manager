"""Tenant isolation for the parent absence makeup state (real Mongo repo)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from backend.v2.contexts.enrollment.application.use_cases.makeup_requests import (
    DescribeAbsenceMakeups,
)
from backend.v2.tests.application.test_describe_absence_makeups import KEY, NOW, _request
from backend.v2.tests.application.test_makeup_candidates import _Enrollments, _Presence
from backend.v2.tests.application.test_makeup_requests import (
    _absence_notice,
    _enrollment,
    _FakeNotices,
    _FakeOccurrences,
    _FakePolicies,
    _now,
    _occurrence,
)


@pytest.mark.asyncio
async def test_another_academys_booked_request_never_marks_this_absence_booked(db) -> None:
    """Same student and class-date ids in two academies: academy B's approved
    makeup must not leak into academy A's absence state (real Mongo repo)."""
    from backend.v2.contexts.enrollment.infrastructure.mongo_makeup_request_repo import (
        MongoMakeupRequestRepository,
    )
    from backend.v2.shared.tenancy.context import tenant_scope

    repo = MongoMakeupRequestRepository(db)
    with tenant_scope("academy-b"):
        await repo.add(
            _request("approved", approved_target_occurrence_id="occ-b-target").model_copy(
                update={"academy_id": "academy-b"}
            )
        )

    describe = DescribeAbsenceMakeups(
        occurrences=_FakeOccurrences([_occurrence(start_at=NOW - timedelta(days=2))]),
        enrollments=_Enrollments([_enrollment()]),
        notices=_FakeNotices([_absence_notice()]),
        makeups=repo,
        policies=_FakePolicies(),
        attendance=_Presence(),
        clock=_now,
    )
    with tenant_scope("academy-a"):
        result_a = await describe.execute([KEY])
    with tenant_scope("academy-b"):
        result_b = await describe.execute([KEY])

    assert result_a[KEY].state == "eligible"
    assert result_a[KEY].booked_occurrence_id is None
    assert result_b[KEY].state == "booked"
