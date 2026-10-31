"""Indexes for ``payment_disputes``, the Stripe disputes (chargebacks) the
webhook records for each academy (direct charges, slice 6).

A dispute on a direct charge is the academy's own: it is recorded, mirrored
onto the disputed payment row and shown on Billing Health, and the owner is
e-mailed. Two reads:

* ``payment_disputes_academy_dispute_unique``: ``(academy_id, dispute_id)``,
  unique; the upsert key every ``charge.dispute.*`` event writes through.
* ``payment_disputes_academy_open_opened``: ``(academy_id, is_open,
  opened_at desc)``; the Billing Health open-dispute count and list.

Both lead with ``academy_id`` (#849); no partial filter; nothing queries it
with ``$or``. New, empty collection: no data is read or changed. Idempotent:
``create_index`` with the same name and spec is a no-op.
"""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0205_payment_disputes"

#: (collection, name, keys, options). Exposed so the unit test pins the shape.
INDEXES: list[tuple[str, str, list[tuple[str, int]], dict[str, Any]]] = [
    (
        "payment_disputes",
        "payment_disputes_academy_dispute_unique",
        [("academy_id", 1), ("dispute_id", 1)],
        {"unique": True},
    ),
    (
        "payment_disputes",
        "payment_disputes_academy_open_opened",
        [("academy_id", 1), ("is_open", 1), ("opened_at", -1)],
        {},
    ),
]


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    for collection, name, keys, options in INDEXES:
        await db[collection].create_index(keys, name=name, **options)
