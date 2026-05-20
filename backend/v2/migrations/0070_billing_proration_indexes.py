"""Billing proration snapshots and invoice-key indexes."""

from __future__ import annotations


version = "0070_billing_proration_indexes"


async def up(db) -> None:
    snapshots = db["billing_calculation_snapshots"]
    await snapshots.create_index(
        [("academy_id", 1), ("snapshot_id", 1)],
        unique=True,
        name="academy_snapshot_unique",
        partialFilterExpression={"snapshot_id": {"$type": "string"}},
    )
    await snapshots.create_index(
        [("academy_id", 1), ("enrollment_id", 1), ("billing_period_label", 1), ("status", 1)],
        name="academy_enrollment_period_status",
    )
    keys = db["billing_invoice_keys"]
    await keys.create_index(
        [("academy_id", 1), ("enrollment_id", 1), ("period", 1)],
        unique=True,
        name="academy_enrollment_period_unique",
    )
    await db["payments"].create_index(
        [("academy_id", 1), ("calculation_snapshot_id", 1)],
        name="academy_calculation_snapshot",
        partialFilterExpression={"calculation_snapshot_id": {"$type": "string"}},
    )
