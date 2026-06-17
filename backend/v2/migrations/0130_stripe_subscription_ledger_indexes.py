"""Indexes for Stripe subscription invoice ledger convergence."""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0130_stripe_subscription_ledger_indexes"


async def up(db: AsyncIOMotorDatabase) -> None:
    await db["invoices"].create_index(
        [("academy_id", 1), ("stripe_invoice_id", 1)],
        name="academy_stripe_invoice_unique",
        unique=True,
        partialFilterExpression={"stripe_invoice_id": {"$type": "string"}},
    )
    await db["invoices"].create_index(
        [("academy_id", 1), ("enrollment_id", 1), ("period", 1), ("status", 1)],
        name="academy_enrollment_period_status",
    )
    await db["ledger_payments"].create_index(
        [("academy_id", 1), ("stripe_invoice_id", 1)],
        name="academy_ledger_payment_stripe_invoice",
        partialFilterExpression={"stripe_invoice_id": {"$type": "string"}},
    )
    await db["payment_allocations"].create_index(
        [("academy_id", 1), ("idempotency_key", 1)],
        name="academy_allocation_idempotency_unique",
        unique=True,
        partialFilterExpression={"idempotency_key": {"$type": "string"}},
    )
    await db["payment_attempts"].create_index(
        [("academy_id", 1), ("idempotency_key", 1)],
        name="academy_payment_attempt_idempotency_unique",
        unique=True,
        partialFilterExpression={"idempotency_key": {"$type": "string"}},
    )
    await db["payment_attempts"].create_index(
        [("academy_id", 1), ("invoice_id", 1), ("created_at", -1)],
        name="academy_payment_attempt_invoice_history",
    )
    await db["stripe_invoice_processing"].create_index(
        [("academy_id", 1), ("business_key", 1)],
        name="academy_stripe_invoice_processing_business_key_unique",
        unique=True,
    )
