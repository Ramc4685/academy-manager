"""Mongo-backed Stripe event idempotency.

Insert-first lock pattern with a retry path:
- New event: insert succeeds → claim returned True → caller dispatches.
- Concurrent retry while processing: duplicate-key error → claim False.
- Stripe retry of an event that we processed successfully: claim False
  (status=processed) → caller short-circuits and returns 200.
- Stripe retry of an event that previously *failed*: we relax the lock
  back to `processing` and return True so the caller can retry. Without
  this, a transient DB error during dispatch would permanently mark the
  Stripe event "failed" and Stripe's retries would forever be 200/deduped
  while the domain state remains incorrect.

NOT tenant-scoped — Stripe events are globally unique by Stripe event id.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

# A claim sitting in `processing` longer than this is treated as orphaned
# (the previous attempt crashed before completing). Stripe retries will
# reclaim it.
STALE_PROCESSING_AFTER = timedelta(minutes=5)


class MongoStripeEventDedup:
    COLLECTION = "stripe_webhook_events"

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._coll = db[self.COLLECTION]

    async def claim(self, event_id: str, event_type: str) -> bool:
        now = datetime.now(UTC)
        try:
            await self._coll.insert_one(
                {
                    "event_id": event_id,
                    "event_type": event_type,
                    "status": "processing",
                    "received_at": now,
                }
            )
            return True
        except DuplicateKeyError:
            pass

        # Existing row — decide whether the caller should retry or short-circuit.
        existing = await self._coll.find_one({"event_id": event_id})
        if existing is None:
            return False
        status = existing.get("status")
        if status == "processed":
            # Successfully completed previously; short-circuit so caller
            # returns 200 to Stripe without re-dispatching.
            return False
        if status == "failed":
            # Previous attempt failed — reclaim so the caller can retry.
            await self._coll.update_one(
                {"event_id": event_id, "status": "failed"},
                {
                    "$set": {"status": "processing", "received_at": now},
                    "$unset": {"failed_at": "", "error": ""},
                },
            )
            return True
        if status == "processing":
            # Orphaned claim? Reclaim if older than STALE_PROCESSING_AFTER.
            received_at = existing.get("received_at")
            if isinstance(received_at, datetime):
                # Mongo (and mongomock) may return tz-naive datetimes;
                # treat them as UTC for the staleness comparison.
                if received_at.tzinfo is None:
                    received_at = received_at.replace(tzinfo=UTC)
                if (now - received_at) > STALE_PROCESSING_AFTER:
                    result = await self._coll.update_one(
                        {"event_id": event_id, "status": "processing"},
                        {"$set": {"received_at": now}},
                    )
                    if result.modified_count == 1:
                        return True
            return False
        # Unknown status — be conservative; don't reclaim.
        return False

    async def mark_processed(self, event_id: str) -> None:
        await self._coll.update_one(
            {"event_id": event_id},
            {"$set": {"status": "processed", "processed_at": datetime.now(UTC)}},
        )

    async def mark_failed(self, event_id: str, error: str) -> None:
        await self._coll.update_one(
            {"event_id": event_id},
            {
                "$set": {
                    "status": "failed",
                    "failed_at": datetime.now(UTC),
                    "error": error,
                }
            },
        )
