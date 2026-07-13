"""Contract tests for MongoTrialRequestRepository (R3, Task 7).

Verifies CRUD, status filtering, duplicate-pending lookup,
convertible-trial lookup, the atomic pending->decided transition, and
tenant isolation for the new ``trial_requests`` collection.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.enrollment.domain.self_service import TrialRequest
from backend.v2.contexts.enrollment.infrastructure.mongo_trial_request_repo import (
    MongoTrialRequestRepository,
)

NOW = datetime(2026, 7, 10, 8, 0, tzinfo=UTC)


def _trial(
    *,
    request_id: str = "req-1",
    academy_id: str = "test-academy",
    parent_user_id: str = "parent-1",
    session_id: str = "session-1",
    status: str = "pending",
    linked_application_id: str | None = None,
    created_at: datetime = NOW,
) -> TrialRequest:
    return TrialRequest(
        request_id=request_id,
        academy_id=academy_id,
        parent_user_id=parent_user_id,
        student_ref="existing_student",
        student_id="student-1",
        requested_session_id=session_id,
        preferred_start="2026-07-15",
        preferred_end="2026-07-22",
        status=status,  # type: ignore[arg-type]
        linked_application_id=linked_application_id,
        created_at=created_at,
    )


@pytest.mark.asyncio
async def test_add_and_get_round_trips(db, acad):
    repo = MongoTrialRequestRepository(db)
    request = _trial()

    await repo.add(request)
    fetched = await repo.get("req-1")

    assert fetched is not None
    assert fetched.request_id == "req-1"
    assert fetched.parent_user_id == "parent-1"
    assert fetched.status == "pending"


@pytest.mark.asyncio
async def test_get_returns_none_when_missing(db, acad):
    repo = MongoTrialRequestRepository(db)

    assert await repo.get("missing") is None


@pytest.mark.asyncio
async def test_list_for_parent_newest_first(db, acad):
    repo = MongoTrialRequestRepository(db)
    await repo.add(_trial(request_id="req-1", created_at=datetime(2026, 7, 1, tzinfo=UTC)))
    await repo.add(_trial(request_id="req-2", created_at=datetime(2026, 7, 5, tzinfo=UTC)))

    result = await repo.list_for_parent("parent-1")

    assert [r.request_id for r in result] == ["req-2", "req-1"]


@pytest.mark.asyncio
async def test_list_by_status_filters(db, acad):
    repo = MongoTrialRequestRepository(db)
    await repo.add(_trial(request_id="req-1", status="pending"))
    await repo.add(_trial(request_id="req-2", status="approved"))

    pending = await repo.list_by_status("pending")
    all_rows = await repo.list_by_status(None)

    assert [r.request_id for r in pending] == ["req-1"]
    assert len(all_rows) == 2


@pytest.mark.asyncio
async def test_find_pending_for_parent_and_session(db, acad):
    repo = MongoTrialRequestRepository(db)
    await repo.add(_trial(request_id="req-1", status="pending", session_id="session-1"))

    found = await repo.find_pending_for_parent_and_session("parent-1", "session-1")
    not_found = await repo.find_pending_for_parent_and_session("parent-1", "session-2")

    assert found is not None
    assert found.request_id == "req-1"
    assert not_found is None


@pytest.mark.asyncio
async def test_find_latest_convertible_for_parent(db, acad):
    repo = MongoTrialRequestRepository(db)
    await repo.add(
        _trial(
            request_id="req-old",
            status="approved",
            created_at=datetime(2026, 6, 1, tzinfo=UTC),
        )
    )
    await repo.add(
        _trial(
            request_id="req-new",
            status="completed",
            created_at=datetime(2026, 7, 1, tzinfo=UTC),
        )
    )
    await repo.add(
        _trial(
            request_id="req-already-linked",
            status="approved",
            linked_application_id="app-existing",
            created_at=datetime(2026, 7, 5, tzinfo=UTC),
        )
    )

    found = await repo.find_latest_convertible_for_parent("parent-1")

    assert found is not None
    assert found.request_id == "req-new"


@pytest.mark.asyncio
async def test_find_latest_convertible_returns_none_when_no_match(db, acad):
    repo = MongoTrialRequestRepository(db)
    await repo.add(_trial(status="pending"))

    assert await repo.find_latest_convertible_for_parent("parent-1") is None


@pytest.mark.asyncio
async def test_update_persists_changes(db, acad):
    repo = MongoTrialRequestRepository(db)
    request = _trial()
    await repo.add(request)

    updated = request.model_copy(update={"status": "converted", "linked_application_id": "app-1"})
    await repo.update(updated)
    fetched = await repo.get("req-1")

    assert fetched is not None
    assert fetched.status == "converted"
    assert fetched.linked_application_id == "app-1"


@pytest.mark.asyncio
async def test_transition_from_pending_succeeds_once(db, acad):
    repo = MongoTrialRequestRepository(db)
    await repo.add(_trial(status="pending"))

    first = await repo.transition_from_pending("req-1", {"status": "approved"})
    second = await repo.transition_from_pending("req-1", {"status": "denied"})

    assert first is not None
    assert first.status == "approved"
    assert second is None  # already transitioned out of pending; CAS loses cleanly


@pytest.mark.asyncio
async def test_transition_from_pending_returns_none_when_missing(db, acad):
    repo = MongoTrialRequestRepository(db)

    assert await repo.transition_from_pending("missing", {"status": "approved"}) is None


@pytest.mark.asyncio
async def test_tenant_isolation(db, acad):
    # Seed a trial request for a DIFFERENT tenant directly (raw insert bypasses
    # the ContextVar-scoped writer). The acad fixture keeps the current tenant
    # at "test-academy", so tenant-scoped reads must not see "other-academy".
    await db["trial_requests"].insert_one(
        {
            "request_id": "req-other",
            "academy_id": "other-academy",
            "parent_user_id": "parent-1",
            "student_ref": "existing_student",
            "student_id": "student-1",
            "prospective_child_name": None,
            "prospective_child_dob": None,
            "requested_session_id": "session-1",
            "preferred_start": "2026-07-15",
            "preferred_end": "2026-07-22",
            "status": "pending",
            "assigned_occurrence_id": None,
            "linked_application_id": None,
            "denial_reason": None,
            "decided_by": None,
            "decided_at": None,
            "created_at": NOW,
        }
    )
    repo = MongoTrialRequestRepository(db)

    assert await repo.get("req-other") is None
    assert await repo.list_for_parent("parent-1") == []
    assert await repo.list_by_status(None) == []
    assert await repo.find_pending_for_parent_and_session("parent-1", "session-1") is None
    assert await repo.find_latest_convertible_for_parent("parent-1") is None
