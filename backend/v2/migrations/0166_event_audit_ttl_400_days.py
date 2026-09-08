"""Extend the ``event_audit`` TTL from 90 days to 400 days (audit item 7).

``event_audit`` is the only durable record of every dispatched domain event
(``PaymentSucceeded``, ``InvoiceGenerated``, enrollment lifecycle, ...) —
application logs live 30 days in Sentry and about 7 days on Fly, so when a
parent asks "why was I charged in <month>" this collection is what answers.
Migration 0002 created ``completed_at_ttl`` with a 90-day expiry, which is
shorter than the billing cycle it needs to explain; financial audit trails
are normally kept for at least 13 months. 400 days covers a full year plus
the trailing month of dunning/retries.

Mongo lets a TTL be changed in place with ``collMod`` (no index rebuild), so
this is metadata-only and O(1). Idempotent: an index already at 400 days is
left alone; a missing collection/index is created with the new TTL.
"""

from __future__ import annotations

import logging

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0166_event_audit_ttl_400_days"

COLLECTION = "event_audit"
INDEX_NAME = "completed_at_ttl"  # created by migration 0002
TTL_SECONDS = 400 * 24 * 60 * 60

log = logging.getLogger(__name__)


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    audit = db[COLLECTION]
    existing = (await audit.index_information()).get(INDEX_NAME)

    if existing is None:
        await audit.create_index("completed_at", expireAfterSeconds=TTL_SECONDS, name=INDEX_NAME)
        log.info("0166: created %s.%s with %ss TTL", COLLECTION, INDEX_NAME, TTL_SECONDS)
        return

    if existing.get("expireAfterSeconds") == TTL_SECONDS:
        return

    try:
        await db.command(
            {
                "collMod": COLLECTION,
                "index": {"name": INDEX_NAME, "expireAfterSeconds": TTL_SECONDS},
            }
        )
    except NotImplementedError:
        # mongomock has no collMod; rebuilding the index is equivalent there.
        await audit.drop_index(INDEX_NAME)
        await audit.create_index("completed_at", expireAfterSeconds=TTL_SECONDS, name=INDEX_NAME)
    log.info(
        "0166: %s.%s TTL %s -> %ss",
        COLLECTION,
        INDEX_NAME,
        existing.get("expireAfterSeconds"),
        TTL_SECONDS,
    )
