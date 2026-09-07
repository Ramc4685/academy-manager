"""Issue #675: the two CAS writes behind a deferred parent self-cancel."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_repo import (
    MongoEnrollmentRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_writer import (
    MongoEnrollmentWriter,
)
from backend.v2.shared.tenancy.context import tenant_scope

# Mongo stores millisecond precision; mongomock also hands naive stamps back.
MONTH_END = datetime(2026, 9, 30, 23, 59, 59, 999000, tzinfo=UTC)
NOW = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)


def _utc(value: datetime | None) -> datetime | None:
    return value if value is None or value.tzinfo else value.replace(tzinfo=UTC)


def _db(name: str):
    mongomock_motor = pytest.importorskip("mongomock_motor")
    return mongomock_motor.AsyncMongoMockClient()[name]


async def _seed(db, status: str = "active") -> None:
    await db["enrollments"].insert_one(
        {
            "academy_id": "acad-1",
            "enrollment_id": "enr-1",
            "session_id": "session-1",
            "student_id": "student-1",
            "status": status,
        }
    )


async def _mark_pending(writer: MongoEnrollmentWriter):
    return await writer.mark_pending_cancellation_by_parent(
        "enr-1",
        cancellation_reason="moving",
        cancellation_policy_snapshot={"fee_cents": 0},
        pending_cancellation_at=MONTH_END,
        requested_at=NOW,
    )


@pytest.mark.asyncio
async def test_pending_cancellation_keeps_status_active_and_is_visible_to_reads() -> None:
    db = _db("pending-cancel-visible")
    await _seed(db)
    writer = MongoEnrollmentWriter(db)
    with tenant_scope("acad-1"):
        updated = await _mark_pending(writer)
        [row] = await MongoEnrollmentRepository(db).active_for_session("session-1")

    assert updated is not None
    assert updated.status == "active"
    assert _utc(updated.pending_cancellation_at) == MONTH_END
    assert _utc(updated.pending_cancellation_requested_at) == NOW
    assert updated.cancellation_reason == "moving"
    # Status-only roster reads still list the child — and see the marker.
    assert row.enrollment_id == "enr-1"
    assert _utc(row.pending_cancellation_at) == MONTH_END


@pytest.mark.asyncio
async def test_second_pending_request_loses_the_cas() -> None:
    db = _db("pending-cancel-twice")
    await _seed(db)
    writer = MongoEnrollmentWriter(db)
    with tenant_scope("acad-1"):
        assert await _mark_pending(writer) is not None
        assert await _mark_pending(writer) is None


@pytest.mark.asyncio
async def test_pending_request_refused_for_non_active_row() -> None:
    db = _db("pending-cancel-paused")
    await _seed(db, status="paused")
    with tenant_scope("acad-1"):
        assert await _mark_pending(MongoEnrollmentWriter(db)) is None


@pytest.mark.asyncio
async def test_complete_pending_cancellation_flips_and_returns_pre_image() -> None:
    db = _db("pending-cancel-complete")
    await _seed(db)
    writer = MongoEnrollmentWriter(db)
    with tenant_scope("acad-1"):
        await _mark_pending(writer)
        before = await writer.complete_pending_cancellation("enr-1", cancelled_at=MONTH_END)
        after = await writer.get("enr-1")
        active = await MongoEnrollmentRepository(db).active_for_session("session-1")
        audit = await writer.list_cancelled_by_parent()

    assert before is not None and before.status == "active"  # pre-image: held a seat
    assert after is not None
    assert after.status == "cancelled"
    assert after.cancelled_by == "parent"
    assert _utc(after.cancelled_at) == MONTH_END
    assert after.pending_cancellation_at is None
    assert after.cancellation_reason == "moving"
    assert active == []
    assert [e.enrollment_id for e in audit] == ["enr-1"]


@pytest.mark.asyncio
async def test_complete_pending_cancellation_stands_down_when_admin_ended_it_first() -> None:
    db = _db("pending-cancel-admin-first")
    await _seed(db)
    writer = MongoEnrollmentWriter(db)
    with tenant_scope("acad-1"):
        await _mark_pending(writer)
        await writer.update_status("enr-1", "withdrawn")
        assert await writer.complete_pending_cancellation("enr-1", cancelled_at=MONTH_END) is None
        # And never on a row that was not pending at all.
        await db["enrollments"].update_one(
            {"enrollment_id": "enr-1"},
            {"$set": {"status": "active", "pending_cancellation_at": None}},
        )
        assert await writer.complete_pending_cancellation("enr-1", cancelled_at=MONTH_END) is None
