"""Mongo-backed Stripe event idempotency.

Insert-first lock pattern: first writer to insert the row owns the event.
Concurrent retries fail the insert and short-circuit.

NOT tenant-scoped — Stripe events are globally unique by Stripe event id.
"""

from __future__ import annotations

from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError


class MongoStripeEventDedup:
    COLLECTION = "stripe_webhook_events"

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._coll = db[self.COLLECTION]

    async def claim(self, event_id: str, event_type: str) -> bool:
        try:
            await self._coll.insert_one(
                {
                    "event_id": event_id,
                    "event_type": event_type,
                    "status": "processing",
                    "received_at": datetime.now(timezone.utc),
                }
            )
            return True
        except DuplicateKeyError:
            return False

    async def mark_processed(self, event_id: str) -> None:
        await self._coll.update_one(
            {"event_id": event_id},
            {"$set": {"status": "processed", "processed_at": datetime.now(timezone.utc)}},
        )

    async def mark_failed(self, event_id: str, error: str) -> None:
        await self._coll.update_one(
            {"event_id": event_id},
            {
                "$set": {
                    "status": "failed",
                    "failed_at": datetime.now(timezone.utc),
                    "error": error,
                }
            },
        )
