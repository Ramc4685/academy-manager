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
        """Insert-first claim. ``False`` means this event is already accounted for.

        A previously *failed* attempt is reclaimed rather than short-circuited,
        matching ``MongoStripeEventDedup.claim``. Without that, an event whose
        handler raised (say a transient Mongo error while writing the
        suppression) would 500, Resend would retry, the unique index would
        answer "duplicate", and the bounce would be dropped forever — the
        retry the 500 exists to provoke would be silently swallowed.
        """
        now = datetime.now(UTC)
        try:
            await self._events.insert_one(
                {
                    "event_id": event_id,
                    "event_type": event_type,
                    "status": "received",
                    "received_at": now,
                    "processed_at": None,
                    "payload": payload,
                    "error": None,
                    "attempts": 1,
                }
            )
            return True
        except DuplicateKeyError:
            pass

        # An existing row: only a failed attempt may be retried. "received" is
        # an in-flight claim and "processed"/"ignored" are terminal, so both
        # short-circuit to a 200 duplicate.
        result = await self._events.update_one(
            {"event_id": event_id, "status": "failed"},
            {
                "$set": {
                    "status": "received",
                    "event_type": event_type,
                    "received_at": now,
                    "processed_at": None,
                    "payload": payload,
                    "error": None,
                },
                "$inc": {"attempts": 1},
            },
        )
        return bool(result.modified_count)

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
