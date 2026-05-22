"""Mongo repository for platform audit events."""

from __future__ import annotations

from typing import Any

from backend.v2.contexts.platform.audit.domain.models import PlatformAuditEvent


class MongoPlatformAuditRepository:
    """Persists platform audit events in `platform_audit_events`."""

    def __init__(self, db: Any) -> None:
        self._collection = db["platform_audit_events"]

    async def append(self, event: PlatformAuditEvent) -> PlatformAuditEvent:
        await self._collection.insert_one(event.model_dump())
        return event

    async def list_events(
        self,
        *,
        academy_id: str | None = None,
        limit: int = 100,
    ) -> list[PlatformAuditEvent]:
        query: dict[str, Any] = {}
        if academy_id is not None:
            query["academy_id"] = academy_id
        cursor = (
            self._collection.find(query)
            .sort([("created_at", -1), ("audit_event_id", -1)])
            .limit(limit)
        )
        return [PlatformAuditEvent(**doc) async for doc in cursor]
