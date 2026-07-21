"""Distributed job lease for APScheduler jobs.

APScheduler's ``max_instances=1`` only guards against overlap *within a single
process*. When more than one Fly machine runs the app, every scheduled job
fires on every machine, producing duplicate dunning retries, digests, and
webhook processing. This module adds a Mongo-backed lease so exactly one
machine runs a given job per tick.

The claim shape mirrors the outbox dispatcher's atomic
``find_one_and_update`` (``backend/v2/shared/events/dispatcher.py``): a single
conditional update either wins the lease or observes that another worker holds
it. Leases live in ``scheduler_leases`` keyed by the job name (``_id``); the
collection is created implicitly on first upsert, so there is no migration.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

COLLECTION = "scheduler_leases"


async def _acquire(
    db: AsyncIOMotorDatabase[Any],
    name: str,
    ttl: timedelta,
    worker_id: str,
) -> bool:
    """Atomically claim ``name`` for ``ttl``. Returns True iff acquired.

    The lease is free when its ``locked_until`` is missing or in the past. The
    upsert inserts the lease document the first time a job runs; if another
    worker already holds a live lease, the filter fails to match and the upsert
    collides on the ``_id`` unique index, which we read as "not acquired".
    """
    now = datetime.now(UTC)
    try:
        doc = await db[COLLECTION].find_one_and_update(
            {
                "_id": name,
                "$or": [
                    {"locked_until": {"$lte": now}},
                    {"locked_until": None},
                    {"locked_until": {"$exists": False}},
                ],
            },
            {
                "$set": {
                    "locked_until": now + ttl,
                    "lock_owner": worker_id,
                    "updated_at": now,
                }
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError:
        return False
    return doc is not None and doc.get("lock_owner") == worker_id


async def _release(db: AsyncIOMotorDatabase[Any], name: str, worker_id: str) -> None:
    """Release early on clean exit so the next tick can reclaim immediately.

    Guarded by ``lock_owner`` so a worker never clears a lease it has already
    lost to another machine (e.g. after its own lease expired mid-run).
    """
    now = datetime.now(UTC)
    await db[COLLECTION].update_one(
        {"_id": name, "lock_owner": worker_id},
        {"$set": {"locked_until": now, "updated_at": now}},
    )


@asynccontextmanager
async def job_lease(
    db: AsyncIOMotorDatabase[Any],
    name: str,
    ttl: timedelta,
    worker_id: str,
) -> AsyncIterator[bool]:
    """Yield True if this worker holds the lease for ``name``, else False.

    On a clean exit the lease is released early. If the body raises, the lease
    is left to expire after ``ttl`` so a crashed run does not immediately hand
    a half-finished job to the next tick.
    """
    acquired = await _acquire(db, name, ttl, worker_id)
    if not acquired:
        yield False
        return
    try:
        yield True
    except BaseException:
        # Leave the lease to expire; do not release a job that failed midway.
        raise
    else:
        await _release(db, name, worker_id)
