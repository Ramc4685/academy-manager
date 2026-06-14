"""Indexes for the ledger_payments collection (LedgerPayment aggregate).

Mirrors the ledger-payment entries from 0091_billing_ledger_indexes.py, which
added equivalent partial indexes on db.payments.  Now that LedgerPayment has
its own collection (ADR-0011), these are the authoritative indexes for it.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0092_ledger_payments_indexes"


async def up(db: AsyncIOMotorDatabase) -> None:
    coll = db["ledger_payments"]

    # Leading tenant scope — all ledger-payment queries are academy-scoped.
    await coll.create_index(
        [("academy_id", 1)],
        name="academy_id",
    )

    # Idempotency key — unique per academy; partial so NULL keys are excluded.
    await coll.create_index(
        [("academy_id", 1), ("ledger_idempotency_key", 1)],
        unique=True,
        name="academy_ledger_payment_idempotency_unique",
        partialFilterExpression={"ledger_idempotency_key": {"$type": "string"}},
    )

    # payment_id lookup — unique per academy; partial so docs without it are excluded.
    await coll.create_index(
        [("academy_id", 1), ("payment_id", 1)],
        unique=True,
        name="academy_ledger_payment_id_unique",
        partialFilterExpression={"payment_id": {"$type": "string"}},
    )

    # parent_id (e.g. parent/student account) — supports per-parent history queries.
    await coll.create_index(
        [("academy_id", 1), ("parent_id", 1)],
        name="academy_ledger_payments_by_parent",
    )
