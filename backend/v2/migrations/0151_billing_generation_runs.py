"""Unique index for the monthly invoice-generation run record (issue #431).

The scheduler now retries monthly generation every day once an academy's
``billing_day`` has passed, until one run completes without raising, instead
of only firing on an exact ``billing_day == today`` match (a single failed
03:00 run used to skip the whole month silently).

``billing_generation_runs`` is what stops that retry: one document per
``(academy_id, period)``, written after a successful run. The unique index
keeps two scheduler machines from inserting competing records for the same
period through the upsert.

This is a scheduling record, not an invoice guard — duplicate invoices are
prevented by the deterministic invoice ids and the ``billing_invoice_keys``
unique index inside ``generate_monthly_payments``.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0151"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    await db["billing_generation_runs"].create_index(
        [("academy_id", 1), ("period", 1)],
        unique=True,
        name="academy_period_unique",
    )
