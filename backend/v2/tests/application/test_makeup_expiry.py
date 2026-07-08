"""Use-case tests for the makeup-request expiry job (R2, Task 6).

Pending requests whose window has lapsed must flip to ``expired`` so they
never silently linger as actionable-looking "pending" items. Requests already
decided (approved/denied) or completed must never be touched by the job.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.enrollment.application.use_cases.makeup_requests import (
    ExpireMakeupRequests,
)


def _now() -> datetime:
    return datetime(2026, 7, 10, 8, 0, tzinfo=UTC)


class _FakeMakeupsForExpiry:
    """Only exposes ``expire_pending_before`` — mirrors the repo contract the
    use case actually depends on (bulk update, returns count)."""

    def __init__(self, expired_count: int = 0) -> None:
        self.expired_count = expired_count
        self.calls: list[datetime] = []

    async def expire_pending_before(self, now: datetime) -> int:
        self.calls.append(now)
        return self.expired_count


@pytest.mark.asyncio
async def test_expire_makeup_requests_delegates_to_repo_bulk_update() -> None:
    makeups = _FakeMakeupsForExpiry(expired_count=3)
    use_case = ExpireMakeupRequests(makeups=makeups, clock=_now)

    result = await use_case.execute()

    assert result == 3
    assert makeups.calls == [_now()]


@pytest.mark.asyncio
async def test_expire_makeup_requests_returns_zero_when_nothing_expired() -> None:
    makeups = _FakeMakeupsForExpiry(expired_count=0)
    use_case = ExpireMakeupRequests(makeups=makeups, clock=_now)

    result = await use_case.execute()

    assert result == 0


# --- Repo-level behavior (exercised against the real Mongo repo via mongomock) ---


@pytest.mark.asyncio
async def test_repo_expire_pending_before_flips_only_lapsed_pending_requests() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")

    from backend.v2.contexts.enrollment.domain.self_service import MakeupRequest
    from backend.v2.contexts.enrollment.infrastructure.mongo_makeup_request_repo import (
        MongoMakeupRequestRepository,
    )
    from backend.v2.shared.tenancy import tenant_scope

    client = mongomock_motor.AsyncMongoMockClient()
    db = client["test"]
    repo = MongoMakeupRequestRepository(db)

    with tenant_scope("acad"):
        lapsed_pending = MakeupRequest(
            request_id="req-lapsed",
            academy_id="acad",
            student_id="student-1",
            parent_id="parent-1",
            missed_occurrence_id="occ-1",
            status="pending",
            expires_at=_now() - timedelta(days=1),
            created_at=_now() - timedelta(days=10),
        )
        in_window_pending = MakeupRequest(
            request_id="req-in-window",
            academy_id="acad",
            student_id="student-1",
            parent_id="parent-1",
            missed_occurrence_id="occ-2",
            status="pending",
            expires_at=_now() + timedelta(days=1),
            created_at=_now() - timedelta(days=1),
        )
        lapsed_approved = MakeupRequest(
            request_id="req-approved",
            academy_id="acad",
            student_id="student-1",
            parent_id="parent-1",
            missed_occurrence_id="occ-3",
            status="approved",
            expires_at=_now() - timedelta(days=1),
            created_at=_now() - timedelta(days=10),
            decided_by="admin-1",
            decided_at=_now() - timedelta(days=5),
            approved_target_occurrence_id="occ-target",
        )
        for r in (lapsed_pending, in_window_pending, lapsed_approved):
            await repo.add(r)

        count = await repo.expire_pending_before(_now())

        assert count == 1
        assert (await repo.get("req-lapsed")).status == "expired"
        assert (await repo.get("req-in-window")).status == "pending"
        assert (await repo.get("req-approved")).status == "approved"
