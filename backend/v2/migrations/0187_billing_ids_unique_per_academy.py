"""Scope billing id uniqueness to the tenant (issue #849, batch 2).

Migrations 0030, 0111 and 0126 built single-field unique indexes on the BARE
``payments.payment_id``, ``subscriptions.subscription_id``,
``subscriptions.stripe_subscription_id`` and
``student_billing_enrollments.enrollment_id``. Each is globally unique across
every academy, while every reader and writer filters tenant-scoped — the #610
trap that 0162 fixed for ``students`` and 0187 for the enrollment core. The
Stripe webhook is no exception: it resolves the academy at ingest and looks
subscriptions up under ``tenant_scope``, so ``(academy_id,
stripe_subscription_id)`` serves it directly and no single-field index needs
to survive.

Each is replaced with a unique partial index on ``(academy_id, <id>)`` with
``partialFilterExpression={"<id>": {"$gt": ""}}`` — NOT the ``$type:
"string"`` filter 0162 and 0186 used. MongoDB's planner cannot prove that an
equality lookup satisfies a ``$type`` filter, so it never uses such an index
for ``{"academy_id": T, "<id>": X}``; it enforces uniqueness but serves no
read (verified with ``explain()`` on MongoDB 7, and on production after 0186).
``$gt: ""`` is planner-usable for equality and ``$in``, and by type
bracketing still covers strings only: absent, ``null`` and ``""`` stay out of
the constraint. ``MongoSubscriptionRepository.save`` still unsets an empty
``stripe_subscription_id``; with this filter a stray ``""`` no longer
collides either. Migration 0188 re-shapes the 0162/0186 indexes the same way.

``payments`` gets ``payment_id_unique_per_academy``, deliberately NOT the name
``academy_payment_id_unique``: that index belonged to the transitional
ledger-in-payments period, was retired by 0131, and the launch-readiness audit
fails if it reappears.

Safety: every collection is pre-flighted BEFORE any index is touched, so one
dirty collection aborts the whole batch with the offenders named. Per index
the new one is created before the old one is dropped, so uniqueness is never
absent. Re-running is a no-op.

Verified against production on 2026-09-21: all four global indexes present,
no ``(academy_id, <id>)`` twin, zero duplicate pairs, zero docs without a
string ``academy_id``.
"""

from __future__ import annotations

import logging
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0187_billing_ids_unique_per_academy"

log = logging.getLogger(__name__)

#: (collection, id field, old global index, new per-academy index)
TARGETS: list[tuple[str, str, str, str]] = [
    ("payments", "payment_id", "payment_id_unique", "payment_id_unique_per_academy"),
    (
        "subscriptions",
        "subscription_id",
        "subscription_id_unique",
        "subscription_id_unique_per_academy",
    ),
    (
        "subscriptions",
        "stripe_subscription_id",
        "stripe_sub_unique",
        "stripe_sub_unique_per_academy",
    ),
    (
        "student_billing_enrollments",
        "enrollment_id",
        "student_billing_enrollments_id_unique",
        "student_billing_enrollments_id_unique_per_academy",
    ),
]


async def _duplicate_pairs(collection, field: str) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    """(academy_id, <id>) pairs that would break the new index."""
    cursor = collection.aggregate(
        [
            {"$match": {field: {"$gt": ""}}},
            {
                "$group": {
                    "_id": {"academy_id": "$academy_id", "id": f"${field}"},
                    "count": {"$sum": 1},
                }
            },
            {"$match": {"count": {"$gt": 1}}},
            {"$limit": 20},
        ]
    )
    return [doc async for doc in cursor]


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    # Pre-flight every collection before touching a live constraint, so a
    # failure is a readable message and the batch is all-or-nothing.
    problems: list[str] = []
    for collection, field, _old_index, new_index in TARGETS:
        duplicates = await _duplicate_pairs(db[collection], field)
        if duplicates:
            offenders = ", ".join(
                f"{row['_id'].get('academy_id')!r}/{row['_id'].get('id')!r} x{row['count']}"
                for row in duplicates
            )
            problems.append(
                f"{collection} has duplicate (academy_id, {field}) pairs, so "
                f"{new_index} cannot be created (up to 20 shown): {offenders}"
            )
    if problems:
        raise RuntimeError(
            "0187 aborted before changing any index. Deduplicate these first: "
            + "; ".join(problems)
            + ". The old global indexes have been left in place."
        )

    for collection, field, old_index, new_index in TARGETS:
        coll = db[collection]
        # Create first, drop second: uniqueness is never absent in between.
        await coll.create_index(
            [("academy_id", 1), (field, 1)],
            unique=True,
            partialFilterExpression={field: {"$gt": ""}},
            name=new_index,
        )
        existing = await coll.index_information()
        if old_index in existing:
            await coll.drop_index(old_index)
            log.info("0187: dropped globally-unique %s in favour of %s", old_index, new_index)
