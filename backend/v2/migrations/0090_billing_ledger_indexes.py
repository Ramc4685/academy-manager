from __future__ import annotations


version = "0090_billing_ledger_indexes"


async def up(db) -> None:
    await db.invoices.create_index(
        [("academy_id", 1), ("invoice_id", 1)],
        unique=True,
        name="academy_invoice_unique",
    )
    await db.invoices.create_index(
        [("academy_id", 1), ("idempotency_key", 1)],
        unique=True,
        name="academy_invoice_idempotency_unique",
        partialFilterExpression={"idempotency_key": {"$type": "string"}},
    )
    await db.invoices.create_index(
        [("academy_id", 1), ("parent_id", 1), ("status", 1), ("period", 1)],
        name="academy_parent_invoice_status_period",
    )

    await db.invoice_lines.create_index(
        [("academy_id", 1), ("line_id", 1)],
        unique=True,
        name="academy_invoice_line_unique",
    )
    await db.invoice_lines.create_index(
        [("academy_id", 1), ("invoice_id", 1)],
        name="academy_invoice_lines",
    )

    await db.payments.create_index(
        [("academy_id", 1), ("ledger_idempotency_key", 1)],
        unique=True,
        name="academy_payment_ledger_idempotency_unique",
        partialFilterExpression={"ledger_idempotency_key": {"$type": "string"}},
    )
    await db.payments.create_index(
        [("academy_id", 1), ("payment_id", 1)],
        unique=True,
        name="academy_payment_id_unique",
        partialFilterExpression={"payment_id": {"$type": "string"}},
    )

    await db.payment_allocations.create_index(
        [("academy_id", 1), ("allocation_id", 1)],
        unique=True,
        name="academy_allocation_unique",
    )
    await db.payment_allocations.create_index(
        [("academy_id", 1), ("idempotency_key", 1)],
        unique=True,
        name="academy_allocation_idempotency_unique",
        partialFilterExpression={"idempotency_key": {"$type": "string"}},
    )
    await db.payment_allocations.create_index(
        [("academy_id", 1), ("invoice_id", 1)],
        name="academy_invoice_allocations",
    )
    await db.payment_allocations.create_index(
        [("academy_id", 1), ("payment_id", 1)],
        name="academy_payment_allocations",
    )

    await db.account_credit_ledger.create_index(
        [("academy_id", 1), ("source_type", 1), ("source_id", 1)],
        unique=True,
        name="academy_credit_source_unique",
        partialFilterExpression={
            "source_type": {"$type": "string"},
            "source_id": {"$type": "string"},
        },
    )
