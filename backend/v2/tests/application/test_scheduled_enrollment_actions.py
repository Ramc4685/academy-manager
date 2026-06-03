from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.enrollment.application.use_cases.scheduled_actions import (
    ScheduledEnrollmentAction,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_scheduled_action_repo import (
    MongoScheduledEnrollmentActionRepository,
)
from backend.v2.shared.tenancy.context import tenant_scope


def _action(
    action_id: str,
    *,
    pause_request_id: str | None = None,
    run_at: datetime | None = None,
    status: str = "pending",
) -> ScheduledEnrollmentAction:
    now = datetime(2026, 6, 3, 7, 0, tzinfo=UTC)
    return ScheduledEnrollmentAction(
        action_id=action_id,
        academy_id="acad-1",
        action_type="resume_from_pause",
        enrollment_id="enr-1",
        pause_request_id=pause_request_id or f"pause-{action_id}",
        run_at=run_at or now,
        status=status,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_due_actions_return_only_pending_due_rows() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["scheduled-actions-due"]
    repo = MongoScheduledEnrollmentActionRepository(db)
    now = datetime(2026, 6, 3, 7, 0, tzinfo=UTC)

    with tenant_scope("acad-1"):
        await repo.add(_action("due", run_at=now))
        await repo.add(_action("future", run_at=now + timedelta(days=1)))
        await repo.add(_action("done", run_at=now - timedelta(days=1), status="succeeded"))

        due = await repo.list_due(now=now, limit=50)

    assert [row.action_id for row in due] == ["due"]


@pytest.mark.asyncio
async def test_add_is_idempotent_for_same_pause_action() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["scheduled-actions-idempotent"]
    repo = MongoScheduledEnrollmentActionRepository(db)
    action = _action("action-1", pause_request_id="pause-1")

    with tenant_scope("acad-1"):
        await repo.add(action)
        await repo.add(action.model_copy(update={"action_id": "action-2"}))

        due = await repo.list_due(now=action.run_at, limit=50)

    assert [row.action_id for row in due] == ["action-1"]


@pytest.mark.asyncio
async def test_status_transitions_record_attempt_details() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["scheduled-actions-status"]
    repo = MongoScheduledEnrollmentActionRepository(db)
    action = _action("action-1")
    attempted_at = datetime(2026, 6, 3, 8, 0, tzinfo=UTC)

    with tenant_scope("acad-1"):
        await repo.add(action)
        await repo.mark_blocked_capacity("action-1", attempted_at=attempted_at)

        [blocked] = await repo.list_by_status("blocked_capacity", limit=50)
        await repo.mark_failed("action-1", attempted_at=attempted_at, error="stripe failed")
        [failed] = await repo.list_by_status("failed", limit=50)
        await repo.mark_succeeded("action-1", attempted_at=attempted_at)
        [succeeded] = await repo.list_by_status("succeeded", limit=50)

    assert blocked.status == "blocked_capacity"
    assert blocked.attempt_count == 1
    assert failed.status == "failed"
    assert failed.last_error == "stripe failed"
    assert failed.attempt_count == 2
    assert succeeded.status == "succeeded"
    assert succeeded.last_error is None
    assert succeeded.attempt_count == 3
