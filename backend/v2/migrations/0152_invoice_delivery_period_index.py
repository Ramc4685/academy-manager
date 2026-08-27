"""Index the post-generation invoice email pass (issue #430).

``list_undelivered_invoices_for_period`` filters on academy + period +
delivery_status and runs once per academy on every daily generation tick. The
existing ``academy_parent_invoice_status_period`` index is parent-first, so a
query without ``parent_id`` cannot use it and would collection-scan every
invoice the academy has ever issued.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0152_invoice_delivery_period_index"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    await db.invoices.create_index(
        [("academy_id", 1), ("period", 1), ("delivery_status", 1), ("created_at", 1)],
        name="academy_period_delivery_status",
    )
