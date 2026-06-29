"""Billing P0 hardening: invoice optimistic-concurrency version + billing audit log.

- Backfill ``version=0`` on existing invoices so the optimistic-concurrency guard in
  MongoBillingLedgerRepository.save_invoice has a baseline (P0-2).
- Create indexes for the new append-only ``billing_audit_log`` collection (P0-4).
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0135"


async def up(db: AsyncIOMotorDatabase) -> None:
    # P0-2: ensure every invoice has a numeric version for optimistic concurrency.
    await db["invoices"].update_many(
        {"version": {"$exists": False}},
        {"$set": {"version": 0}},
    )

    # P0-4: append-only billing audit trail.
    audit = db["billing_audit_log"]
    await audit.create_index(
        [("academy_id", 1), ("invoice_id", 1), ("at", -1)],
        name="academy_invoice_at",
    )
    await audit.create_index(
        [("academy_id", 1), ("at", -1)],
        name="academy_at",
    )
    await audit.create_index(
        [("academy_id", 1), ("audit_id", 1)],
        name="academy_audit_id_unique",
        unique=True,
    )
