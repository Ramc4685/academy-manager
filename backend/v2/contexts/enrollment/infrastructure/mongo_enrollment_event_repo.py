"""Tenant-scoped enrollment lifecycle event history."""

from __future__ import annotations

from typing import Any

from backend.v2.contexts.enrollment.domain.events import EnrollmentLifecycleEvent
from backend.v2.shared.tenancy import TenantScopedRepository


class MongoEnrollmentEventRepository(TenantScopedRepository):
    collection_name = "enrollment_events"

    @staticmethod
    def _to_domain(doc: dict[str, Any]) -> EnrollmentLifecycleEvent:
        return EnrollmentLifecycleEvent(
            event_id=str(doc["event_id"]),
            academy_id=str(doc["academy_id"]),
            event_type=doc["event_type"],
            enrollment_id=doc.get("enrollment_id"),
            waitlist_id=doc.get("waitlist_id"),
            session_id=doc.get("session_id"),
            from_session_id=doc.get("from_session_id"),
            to_session_id=doc.get("to_session_id"),
            student_id=str(doc["student_id"]),
            actor_id=doc.get("actor_id"),
            reason=doc.get("reason"),
            effective_at=doc["effective_at"],
            occurred_at=doc["occurred_at"],
            billing_policy=doc.get("billing_policy"),
            billing_result=doc.get("billing_result"),
            credit_id=doc.get("credit_id"),
            refund_id=doc.get("refund_id"),
            metadata=doc.get("metadata", {}),
        )

    async def record(self, event: EnrollmentLifecycleEvent) -> None:
        doc = event.model_dump(mode="python")
        values = {k: v for k, v in doc.items() if k != "academy_id"}
        await self._update_one(
            {"event_id": event.event_id},
            {"$setOnInsert": values},
            upsert=True,
        )

    async def list_for_enrollment(self, enrollment_id: str) -> list[EnrollmentLifecycleEvent]:
        cursor = self._find_many(
            {"enrollment_id": enrollment_id},
            sort=[("occurred_at", 1), ("event_id", 1)],
        )
        return [self._to_domain(doc) async for doc in cursor]
