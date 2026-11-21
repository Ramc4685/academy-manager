"""Plain index on ``ledger_payments.stripe_payment_intent_id`` (#982).

Ingest attributes a platform dispute (no Connect account, no metadata) to the
academy whose ledger payment recorded the disputed PaymentIntent. That lookup
runs before any tenant scope, so the per-academy unique index from 0173 (led
by ``academy_id``) cannot serve it. Non-unique: uniqueness stays per academy.
The partial filter is ``$gt ""`` so the planner can use it for equality.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0245_ledger_payment_intent_directory_index"

INDEX_NAME = "ledger_payment_intent_directory_lookup"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    await db["ledger_payments"].create_index(
        "stripe_payment_intent_id",
        partialFilterExpression={"stripe_payment_intent_id": {"$gt": ""}},
        name=INDEX_NAME,
    )
