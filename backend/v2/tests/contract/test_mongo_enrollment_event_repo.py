from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.v2.contexts.enrollment.domain.events import EnrollmentLifecycleEvent
from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_event_repo import (
    MongoEnrollmentEventRepository,
)
from backend.v2.shared.tenancy.context import tenant_scope


def _event(
    event_id: str,
    *,
    academy_id: str,
    enrollment_id: str = "enr-1",
    event_type: str = "paused",
    occurred_at: datetime,
) -> EnrollmentLifecycleEvent:
    return EnrollmentLifecycleEvent(
        event_id=event_id,
        academy_id=academy_id,
        enrollment_id=enrollment_id,
        waitlist_id=None,
        event_type=event_type,  # type: ignore[arg-type]
        session_id="sess-1",
        from_session_id=None,
        to_session_id=None,
        student_id="stu-1",
        actor_id="admin-1",
        reason="requested",
        effective_at=occurred_at,
        occurred_at=occurred_at,
    )


@pytest.mark.asyncio
async def test_records_and_lists_enrollment_timeline_in_order(db) -> None:
    repo = MongoEnrollmentEventRepository(db)
    first = datetime(2026, 5, 21, 12, 0, tzinfo=timezone.utc)
    second = datetime(2026, 5, 21, 13, 0, tzinfo=timezone.utc)

    with tenant_scope("academy-a"):
        await repo.record(_event("evt-2", academy_id="academy-a", occurred_at=second))
        await repo.record(_event("evt-1", academy_id="academy-a", occurred_at=first))

        rows = await repo.list_for_enrollment("enr-1")

    assert [row.event_id for row in rows] == ["evt-1", "evt-2"]
    assert [row.academy_id for row in rows] == ["academy-a", "academy-a"]


@pytest.mark.asyncio
async def test_enrollment_event_repo_isolates_tenants(db) -> None:
    repo = MongoEnrollmentEventRepository(db)
    at = datetime(2026, 5, 21, 12, 0, tzinfo=timezone.utc)

    with tenant_scope("academy-a"):
        await repo.record(_event("evt-a", academy_id="academy-a", occurred_at=at))
    with tenant_scope("academy-b"):
        await repo.record(_event("evt-b", academy_id="academy-b", occurred_at=at))

    with tenant_scope("academy-a"):
        rows = await repo.list_for_enrollment("enr-1")

    assert [row.event_id for row in rows] == ["evt-a"]
