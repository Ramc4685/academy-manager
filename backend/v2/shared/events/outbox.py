"""Outbox — durable event storage written in the same transaction as aggregates."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from motor.motor_asyncio import AsyncIOMotorClientSession, AsyncIOMotorDatabase

from .base import DomainEvent


class Outbox(Protocol):
    """Append-only event store. Writes happen inside the same Mongo
    transaction as the aggregate change to guarantee at-least-once delivery.
    """

    async def append(
        self,
        event: DomainEvent,
        *,
        session: AsyncIOMotorClientSession | None = None,
    ) -> None: ...


class MongoOutbox:
    """Mongo-backed Outbox.

    Collection: ``outbox_events``. Indexes created by migration P0-16.
    """

    COLLECTION = "outbox_events"

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._collection = db[self.COLLECTION]

    async def append(
        self,
        event: DomainEvent,
        *,
        session: AsyncIOMotorClientSession | None = None,
    ) -> None:
        now = datetime.now(UTC)
        await self._collection.insert_one(
            {
                "event_id": event.event_id,
                "name": event.name,
                "schema_version": event.schema_version,
                "aggregate_id": event.aggregate_id,
                "academy_id": event.academy_id,
                "occurred_at": event.occurred_at,
                "payload": event.model_dump(mode="json"),
                "processed": False,
                "status": "pending",
                "attempt_count": 0,
                "next_retry_at": now,
                "locked_until": None,
                "lock_owner": None,
                "created_at": now,
                "updated_at": now,
            },
            session=session,
        )
