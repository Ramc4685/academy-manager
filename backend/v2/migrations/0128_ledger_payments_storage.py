"""Move ledger payment storage to its own collection.

This migration is intentionally copy-only. It creates the new collection
indexes and copies ledger-shaped rows from the legacy shared ``payments``
collection into ``ledger_payments``. Deleting copied rows from ``payments`` is a
separate operational cleanup after count verification and rollback signoff.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0128_ledger_payments_storage"

_LEDGER_PAYMENT_SHAPE = {
    "academy_id": {"$type": "string"},
    "payment_id": {"$type": "string"},
    "$or": [
        {"ledger_idempotency_key": {"$type": "string"}},
        {"unapplied_amount_cents": {"$exists": True}},
    ],
}


async def up(db: AsyncIOMotorDatabase) -> None:
    ledger_payments = db["ledger_payments"]
    await ledger_payments.create_index(
        [("academy_id", 1), ("ledger_idempotency_key", 1)],
        unique=True,
        name="academy_ledger_payment_idempotency_unique",
        partialFilterExpression={"ledger_idempotency_key": {"$type": "string"}},
    )
    await ledger_payments.create_index(
        [("academy_id", 1), ("payment_id", 1)],
        unique=True,
        name="academy_ledger_payment_id_unique",
        partialFilterExpression={"payment_id": {"$type": "string"}},
    )
    await ledger_payments.create_index(
        [("academy_id", 1), ("parent_id", 1), ("paid_at", -1)],
        name="academy_ledger_payment_parent_paid_at",
    )

    source_count = await db["payments"].count_documents(_LEDGER_PAYMENT_SHAPE)
    copied = 0
    async for doc in db["payments"].find(_LEDGER_PAYMENT_SHAPE):
        doc.pop("_id", None)
        await ledger_payments.replace_one(
            {"academy_id": doc["academy_id"], "payment_id": doc["payment_id"]},
            doc,
            upsert=True,
        )
        copied += 1

    if copied != source_count:
        raise RuntimeError(
            f"ledger payment copy count mismatch: copied={copied} source={source_count}"
        )
