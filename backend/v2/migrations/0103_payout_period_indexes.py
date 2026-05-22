"""Indexes for the persisted payout-period collections (Wave 5A Stream J).

Two collections:

- ``payout_periods``: one document per (academy_id, coach_id,
  period_start, period_end). Unique on that tuple — it is the natural
  idempotency key for ``GeneratePayoutPeriod``.
- ``payout_period_lines``: one document per occurrence per period. Lines
  are queried via the parent ``period_id`` plus tenancy scope.

The collections are tenant-scoped through ``TenantScopedRepository`` and
``academy_id`` participates in every index — we never query without it.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0103_payout_period_indexes"


async def up(db: AsyncIOMotorDatabase) -> None:
    await db.payout_periods.create_index(
        [
            ("academy_id", 1),
            ("coach_id", 1),
            ("period_start", 1),
            ("period_end", 1),
        ],
        name="payout_periods_natural_key",
        unique=True,
    )
    await db.payout_periods.create_index(
        [("academy_id", 1), ("period_id", 1)],
        name="payout_periods_id",
        unique=True,
    )
    await db.payout_periods.create_index(
        [("academy_id", 1), ("status", 1), ("period_end", -1)],
        name="payout_periods_tenant_status_end",
    )
    await db.payout_period_lines.create_index(
        [("academy_id", 1), ("period_id", 1)],
        name="payout_period_lines_period",
    )
    await db.payout_period_lines.create_index(
        [("academy_id", 1), ("occurrence_id", 1)],
        name="payout_period_lines_occurrence",
    )
