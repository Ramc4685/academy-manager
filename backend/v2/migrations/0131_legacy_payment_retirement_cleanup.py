"""Retire stale legacy payment ownership indexes.

This migration is intentionally non-destructive for ``payments`` rows. The
actual legacy-payment document archive/delete step is operator-controlled via
``backend.scripts.archive_legacy_payments`` after ledger backfill and
reconciliation are verified.
"""

from __future__ import annotations

from contextlib import suppress
from datetime import UTC, datetime

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0131_legacy_payment_retirement_cleanup"


async def _drop_index_if_exists(collection, name: str) -> None:
    indexes = await collection.index_information()
    if name in indexes:
        with suppress(Exception):
            await collection.drop_index(name)


async def up(db: AsyncIOMotorDatabase) -> None:
    now = datetime.now(UTC)

    # Parent Stripe customer ownership moved from users to the tenant-scoped
    # billing mapping in migration 0129. Preserve any remaining values before
    # removing the identity-owned copy.
    cursor = db["users"].find(
        {
            "academy_id": {"$type": "string"},
            "user_id": {"$type": "string"},
            "stripe_customer_id": {"$type": "string"},
        },
        {"academy_id": 1, "user_id": 1, "stripe_customer_id": 1},
    )
    async for user in cursor:
        await db["parent_billing_customers"].update_one(
            {"academy_id": user["academy_id"], "parent_id": user["user_id"]},
            {
                "$set": {
                    "stripe_customer_id": user["stripe_customer_id"],
                    "updated_at": now,
                },
                "$setOnInsert": {
                    "academy_id": user["academy_id"],
                    "parent_id": user["user_id"],
                    "created_at": now,
                },
            },
            upsert=True,
        )

    await db["users"].update_many({}, {"$unset": {"stripe_customer_id": ""}})
    await _drop_index_if_exists(db["users"], "stripe_customer_unique")

    # These indexes belonged to the transitional period where ledger-shaped
    # payment documents could still appear in the legacy payments collection.
    # Ledger idempotency now belongs to ledger_payments, and Stripe invoice
    # uniqueness belongs to invoices.
    payments = db["payments"]
    await _drop_index_if_exists(payments, "academy_payment_ledger_idempotency_unique")
    await _drop_index_if_exists(payments, "academy_payment_id_unique")
    await _drop_index_if_exists(payments, "academy_stripe_invoice_unique")
