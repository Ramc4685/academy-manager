"""Mongo repository for scheduled enrollment actions."""

from __future__ import annotations

from datetime import UTC, datetime

from backend.v2.contexts.enrollment.application.use_cases.scheduled_actions import (
    ScheduledActionStatus,
    ScheduledEnrollmentAction,
)
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoScheduledEnrollmentActionRepository(TenantScopedRepository):
    collection_name = "scheduled_enrollment_actions"

    @staticmethod
    def _to_domain(doc: dict[str, object]) -> ScheduledEnrollmentAction:
        return ScheduledEnrollmentAction(
            action_id=str(doc["action_id"]),
            academy_id=str(doc["academy_id"]),
            action_type=doc["action_type"],
            enrollment_id=str(doc["enrollment_id"]),
            pause_request_id=str(doc["pause_request_id"]),
            run_at=doc["run_at"],
            status=doc.get("status", "pending"),
            attempt_count=int(doc.get("attempt_count") or 0),
            last_attempt_at=doc.get("last_attempt_at"),
            last_error=doc.get("last_error"),
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
        )

    async def add(self, action: ScheduledEnrollmentAction) -> None:
        doc = action.model_dump(mode="python")
        await self._update_one(
            {
                "pause_request_id": action.pause_request_id,
                "action_type": action.action_type,
            },
            {"$setOnInsert": doc},
            upsert=True,
        )

    async def list_due(
        self,
        *,
        now: datetime,
        limit: int = 50,
    ) -> list[ScheduledEnrollmentAction]:
        cursor = self._find_many(
            {"status": "pending", "run_at": {"$lte": now}},
            sort=[("run_at", 1), ("created_at", 1)],
            limit=limit,
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def list_by_status(
        self,
        status: ScheduledActionStatus,
        *,
        limit: int = 50,
    ) -> list[ScheduledEnrollmentAction]:
        cursor = self._find_many(
            {"status": status},
            sort=[("updated_at", -1), ("created_at", 1)],
            limit=limit,
        )
        return [self._to_domain(doc) async for doc in cursor]

    async def mark_succeeded(self, action_id: str, *, attempted_at: datetime) -> None:
        await self._transition(
            action_id,
            status="succeeded",
            attempted_at=attempted_at,
            last_error=None,
        )

    async def mark_blocked_capacity(self, action_id: str, *, attempted_at: datetime) -> None:
        await self._transition(
            action_id,
            status="blocked_capacity",
            attempted_at=attempted_at,
            last_error="session is full",
        )

    async def mark_failed(
        self,
        action_id: str,
        *,
        attempted_at: datetime,
        error: str,
    ) -> None:
        await self._transition(
            action_id,
            status="failed",
            attempted_at=attempted_at,
            last_error=error,
        )

    async def cancel_pending_for_enrollment(self, enrollment_id: str, *, reason: str) -> int:
        # Issue #651: a cancelled session must not leave a pending resume
        # behind — it would try to reserve a seat in a class that no longer runs.
        now = datetime.now(UTC)
        result = await self.collection.update_many(
            self._scoped({"enrollment_id": enrollment_id, "status": "pending"}),
            {"$set": {"status": "cancelled", "last_error": reason, "updated_at": now}},
        )
        return int(result.modified_count or 0)

    async def _transition(
        self,
        action_id: str,
        *,
        status: ScheduledActionStatus,
        attempted_at: datetime,
        last_error: str | None,
    ) -> None:
        await self._update_one(
            {"action_id": action_id},
            {
                "$set": {
                    "status": status,
                    "last_attempt_at": attempted_at,
                    "last_error": last_error,
                    "updated_at": attempted_at,
                },
                "$inc": {"attempt_count": 1},
            },
        )
