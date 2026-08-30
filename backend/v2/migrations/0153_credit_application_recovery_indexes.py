"""Index credit-application lookup by invoice (issue #233).

Orphan monthly-invoice recovery now derives the already-applied credit amount
from ``account_credit_ledger`` — the source of truth, because the per-invoice
application record is written in the same atomic update as the balance
decrement. That lookup filters on ``applied_invoice_ids`` / the new embedded
``applications.invoice_id``, neither of which was indexed, so every recovery
collection-scanned the academy's whole credit history.

Both are multikey (array) indexes, hence two separate indexes rather than one
compound: MongoDB permits at most one array field per index.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0153_credit_application_recovery_indexes"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    await db.account_credit_ledger.create_index(
        [("academy_id", 1), ("applied_invoice_ids", 1)],
        name="academy_credit_applied_invoice_ids",
    )
    await db.account_credit_ledger.create_index(
        [("academy_id", 1), ("applications.invoice_id", 1)],
        name="academy_credit_application_invoice",
    )
