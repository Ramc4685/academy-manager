"""Mongo-backed idempotency lock for inbound email-provider webhooks.

Mirrors ``MongoStripeEventDedup``'s insert-first pattern: the unique index on
``event_id`` IS the guard, so Resend's at-least-once retries can never apply
the same bounce twice. A duplicate is a 200 with ``{"status": "duplicate"}``,
never a 4xx — a 4xx would make Resend retry, then eventually disable the
endpoint.

NOT tenant-scoped: a provider event is globally unique by its ``svix-id`` and
carries no academy.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pymongo.errors import DuplicateKeyError


class MongoEmailProviderEventDedup:
    collection_name = "email_provider_events"

    def __init__(self, db: Any) -> None:
        self._events = db[self.collection_name]

    async def claim(self, *, event_id: str, event_type: str, payload: dict[str, Any]) -> bool:
        """Insert-first claim. ``False`` means this event was already seen."""
        try:
            await self._events.insert_one(
                {
                    "event_id": event_id,
                    "event_type": event_type,
                    "status": "received",
                    "received_at": datetime.now(UTC),
                    "processed_at": None,
                    "payload": payload,
                    "error": None,
                }
            )
            return True
        except DuplicateKeyError:
            return False

    async def mark_processed(self, event_id: str, *, status: str = "processed") -> None:
        await self._events.update_one(
            {"event_id": event_id},
            {"$set": {"status": status, "processed_at": datetime.now(UTC), "error": None}},
        )

    async def mark_failed(self, event_id: str, error: str) -> None:
        await self._events.update_one(
            {"event_id": event_id},
            {"$set": {"status": "failed", "processed_at": datetime.now(UTC), "error": error}},
        )
