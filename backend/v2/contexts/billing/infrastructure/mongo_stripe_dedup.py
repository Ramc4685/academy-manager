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
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument
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
                    "processing_started_at": now,
                    "processing_locked_until": now + STALE_PROCESSING_AFTER,
                    "retry_count": 1,
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
                    "$set": {
                        "status": "processing",
                        "processing_started_at": now,
                        "processing_locked_until": now + STALE_PROCESSING_AFTER,
                        "last_attempt_at": now,
                    },
                    "$unset": {"failed_at": "", "error": "", "error_message": ""},
                    "$inc": {"retry_count": 1},
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
                        {
                            "$set": {
                                "processing_started_at": now,
                                "processing_locked_until": now + STALE_PROCESSING_AFTER,
                                "last_attempt_at": now,
                            },
                            "$inc": {"retry_count": 1},
                        },
                    )
                    if result.modified_count == 1:
                        return True
            return False
        # Unknown status — be conservative; don't reclaim.
        return False

    async def store_received(
        self,
        event: dict[str, Any],
        *,
        raw_payload: bytes,
        academy_id: str,
    ) -> bool:
        event_id = str(event.get("id") or "")
        event_type = str(event.get("type") or "")
        if await self._coll.find_one({"event_id": event_id}, {"_id": 1}) is not None:
            return False
        obj = event.get("data", {}).get("object", {})
        if not isinstance(obj, dict):
            obj = {}
        now = datetime.now(UTC)
        try:
            await self._coll.insert_one(
                {
                    "event_id": event_id,
                    "event_type": event_type,
                    "livemode": bool(event.get("livemode", False)),
                    "stripe_account": event.get("account"),
                    "api_version": event.get("api_version"),
                    "academy_id": academy_id,
                    "object_id": obj.get("id"),
                    "object_type": obj.get("object"),
                    "received_at": now,
                    "status": "received",
                    "processing_started_at": None,
                    "processing_locked_until": None,
                    "processor_id": None,
                    "last_attempt_at": None,
                    "next_retry_at": now,
                    "processed_at": None,
                    "retry_count": 0,
                    "error_message": None,
                    "raw_payload": raw_payload.decode("utf-8"),
                }
            )
            return True
        except DuplicateKeyError:
            return False

    async def claim_next(
        self,
        *,
        academy_id: str,
        processor_id: str,
        lock_seconds: int = 300,
    ) -> dict[str, Any] | None:
        now = datetime.now(UTC)
        lock_until = now + timedelta(seconds=lock_seconds)
        return await self._coll.find_one_and_update(
            {
                "academy_id": academy_id,
                "$or": [
                    {
                        "$and": [
                            {"status": {"$in": ["received", "failed"]}},
                            {
                                "$or": [
                                    {"next_retry_at": {"$exists": False}},
                                    {"next_retry_at": None},
                                    {"next_retry_at": {"$lte": now}},
                                ]
                            },
                        ]
                    },
                    {
                        "$and": [
                            {"status": "processing"},
                            {"processing_locked_until": {"$lt": now}},
                        ]
                    },
                ],
            },
            {
                "$set": {
                    "status": "processing",
                    "processing_started_at": now,
                    "processing_locked_until": lock_until,
                    "processor_id": processor_id,
                    "last_attempt_at": now,
                    "error_message": None,
                },
                "$inc": {"retry_count": 1},
            },
            sort=[("received_at", 1), ("event_id", 1)],
            return_document=ReturnDocument.AFTER,
        )

    async def mark_processed(self, event_id: str) -> None:
        await self._coll.update_many(
            {"event_id": event_id},
            {
                "$set": {
                    "status": "processed",
                    "processed_at": datetime.now(UTC),
                    "processing_locked_until": None,
                    "processor_id": None,
                    "next_retry_at": None,
                    "error_message": None,
                }
            },
        )

    async def mark_failed(self, event_id: str, error: str) -> None:
        now = datetime.now(UTC)
        existing = await self._coll.find_one({"event_id": event_id})
        retry_count = int((existing or {}).get("retry_count") or 0)
        delay = self._retry_delay(retry_count)
        await self._coll.update_many(
            {"event_id": event_id},
            {
                "$set": {
                    "status": "failed",
                    "failed_at": now,
                    "last_attempt_at": now,
                    "next_retry_at": now + delay,
                    "processing_locked_until": None,
                    "processor_id": None,
                    "error": error,
                    "error_message": error,
                }
            },
        )

    async def mark_quarantined(self, event_id: str, error: str) -> None:
        now = datetime.now(UTC)
        await self._coll.update_many(
            {"event_id": event_id},
            {
                "$set": {
                    "status": "quarantined",
                    "last_attempt_at": now,
                    "processing_locked_until": None,
                    "processor_id": None,
                    "next_retry_at": None,
                    "error_message": error,
                }
            },
        )

    @staticmethod
    def _retry_delay(retry_count: int) -> timedelta:
        attempt_index = max(retry_count - 1, 0)
        if attempt_index == 0:
            return timedelta(minutes=1)
        if attempt_index == 1:
            return timedelta(minutes=5)
        if attempt_index == 2:
            return timedelta(minutes=15)
        return timedelta(hours=1)

    @staticmethod
    def _metadata_from_object(obj: dict[str, Any]) -> dict[str, str]:
        metadata = obj.get("metadata")
        if isinstance(metadata, dict):
            return {str(k): str(v) for k, v in metadata.items() if v is not None}
        parent = obj.get("parent")
        if isinstance(parent, dict):
            details = parent.get("subscription_details")
            if isinstance(details, dict) and isinstance(details.get("metadata"), dict):
                return {str(k): str(v) for k, v in details["metadata"].items() if v is not None}
        return {}
