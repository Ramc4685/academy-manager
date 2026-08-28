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

Retries are bounded (issue #437). An event that keeps failing is auto-quarantined
after ``MAX_WEBHOOK_ATTEMPTS``; ``quarantined`` therefore means "a human needs to
look at this", and ``failed`` keeps meaning "still retrying". Without the cap a
poisoned event retried hourly forever and took one of the 25 slots in every
drain tick with it, delaying real payment events.

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

# Issue #437: how many attempts an event gets before it is auto-quarantined.
# The backoff is 1m, 5m, 15m, then hourly, so 24 attempts is roughly a day of
# trying — long enough to ride out any outage worth retrying through, short
# enough that a genuinely poisoned event stops competing for the 25 slots in
# each drain tick instead of looping for weeks.
MAX_WEBHOOK_ATTEMPTS = 24

# Why an event is in `quarantined`. Kept distinct so "retried until we gave up"
# can be told apart from "a guard deliberately rejected this", and so any future
# automatic replay sweep has a precise predicate to select on rather than
# guessing from an error string.
QUARANTINE_RETRY_LIMIT = "retry_limit_exceeded"
QUARANTINE_REJECTED = "rejected_by_guard"


class MongoStripeEventDedup:
    COLLECTION = "stripe_webhook_events"

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._coll = db[self.COLLECTION]

    async def count_stuck_by_status(self, *, academy_id: str) -> dict[str, int]:
        """Real counts of stuck webhook events for one academy (issue #432).

        The admin Billing Health page used to count the length of a list route
        capped at 50, so "50 quarantined" meant anything from 50 to 5,000.

        ``academy_id`` is a required keyword rather than read from the tenant
        ContextVar because this class is not a ``TenantScopedRepository`` — its
        write paths run inside the Stripe webhook, before a tenant is resolved.
        Making the caller pass the request tenant keeps a missing filter a
        visible mistake instead of a silent cross-tenant read.
        """
        counts = {"quarantined": 0, "failed": 0}
        cursor = self._coll.aggregate(
            [
                {
                    "$match": {
                        "academy_id": academy_id,
                        "status": {"$in": ["quarantined", "failed"]},
                    }
                },
                {"$group": {"_id": "$status", "total": {"$sum": 1}}},
            ]
        )
        async for row in cursor:
            status = row.get("_id")
            if status in counts:
                counts[status] = int(row.get("total") or 0)
        return counts

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

    async def mark_failed(self, event_id: str, error: str) -> str:
        """Record a failed attempt, or auto-quarantine once attempts run out.

        Returns the resulting status — ``"failed"`` or ``"quarantined"`` — so the
        caller can alert on the moment an event gives up. Before #437 there was
        no cap at all: a permanently poisoned event retried 1m/5m/15m/hourly
        forever, visible only as a log counter, while occupying one of the 25
        slots in every drain tick and so delaying real payment events.

        The transition to ``quarantined`` happens exactly once, because a
        quarantined event is never claimed again — that is what makes alerting
        here a single alert per event rather than one per retry.
        """
        now = datetime.now(UTC)
        existing = await self._coll.find_one({"event_id": event_id})
        retry_count = int((existing or {}).get("retry_count") or 0)
        if retry_count >= MAX_WEBHOOK_ATTEMPTS:
            await self.mark_quarantined(
                event_id,
                f"gave up after {retry_count} attempts; last error: {error}",
                reason_code=QUARANTINE_RETRY_LIMIT,
            )
            return "quarantined"
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
        return "failed"

    async def mark_quarantined(
        self, event_id: str, error: str, *, reason_code: str = QUARANTINE_REJECTED
    ) -> None:
        now = datetime.now(UTC)
        await self._coll.update_many(
            {"event_id": event_id},
            {
                "$set": {
                    "status": "quarantined",
                    "last_attempt_at": now,
                    "quarantined_at": now,
                    "quarantine_reason": reason_code,
                    "processing_locked_until": None,
                    "processor_id": None,
                    "next_retry_at": None,
                    "error_message": error,
                }
            },
        )

    async def replay(self, event_id: str, *, academy_id: str | None = None) -> bool:
        """Reset a quarantined event back to ``received`` so the drain job
        re-processes it. Only acts on quarantined events (idempotent / safe).

        ``academy_id`` scopes the reset to one tenant — callers MUST pass it so
        an admin cannot replay another academy's event.
        """
        now = datetime.now(UTC)
        query: dict[str, Any] = {"event_id": event_id, "status": "quarantined"}
        if academy_id is not None:
            query["academy_id"] = academy_id
        result = await self._coll.update_many(
            query,
            {
                "$set": {
                    "status": "received",
                    "next_retry_at": now,
                    "retry_count": 0,
                    # Clear the quarantine metadata too, or a replayed event
                    # would keep claiming it gave up while it is running again.
                    "quarantine_reason": None,
                    "quarantined_at": None,
                    "processing_locked_until": None,
                    "processor_id": None,
                    "error_message": None,
                },
            },
        )
        return result.matched_count > 0

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
