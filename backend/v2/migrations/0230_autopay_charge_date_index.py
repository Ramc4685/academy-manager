"""Index the dunning scan's stamped-invoice query (L8 billing calendar).

``prepare_due_states`` now runs two queries instead of one: invoices stamped
with an ``autopay_charge_date`` by that date, then unstamped invoices by
``due_date`` (0156). Two queries rather than an ``$or``, because the planner
does not use partial indexes under an ``$or``.

Mirrors 0156: partial on ``balance_due_cents > 0``, plus
``autopay_charge_date > 1970-01-01`` so the many unstamped invoices (stored as
``null``) stay out of the index. The query repeats that bound so the planner
can prove it matches the filter (a ``$type`` filter would not be used).
"""

from __future__ import annotations

from datetime import datetime

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0230_autopay_charge_date_index"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    await db.invoices.create_index(
        [("academy_id", 1), ("status", 1), ("autopay_charge_date", 1), ("invoice_id", 1)],
        name="academy_invoice_status_autopay_charge_date",
        partialFilterExpression={
            "balance_due_cents": {"$gt": 0},
            "autopay_charge_date": {"$gt": datetime(1970, 1, 1)},
        },
    )
