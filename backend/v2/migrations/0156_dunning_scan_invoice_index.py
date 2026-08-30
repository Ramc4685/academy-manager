"""Index the hourly dunning scan's invoice query (issue #513).

``prepare_due_states`` filters invoices on ``academy_id`` + ``status`` +
``due_date`` (plus ``balance_due_cents > 0``) and sorts on
``(due_date, invoice_id)``. None of the existing invoice indexes
(0091/0112/0138/0152) cover the status+due_date shape, so every hourly tick
collection-scanned and in-memory-sorted the academy's whole invoice set.

The index is partial on ``balance_due_cents > 0`` — the scan only ever wants
invoices with an outstanding balance, and the partial predicate keeps fully
paid history out of the index.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0156_dunning_scan_invoice_index"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    await db.invoices.create_index(
        [("academy_id", 1), ("status", 1), ("due_date", 1), ("invoice_id", 1)],
        name="academy_invoice_status_due_date",
        partialFilterExpression={"balance_due_cents": {"$gt": 0}},
    )
