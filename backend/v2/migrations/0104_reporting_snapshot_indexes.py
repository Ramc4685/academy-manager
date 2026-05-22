"""Indexes for the three reporting snapshot collections (Wave 5A Stream M).

Each snapshot collection has a natural key that the use-case upsert
filter relies on:

- ``academy_revenue_snapshots``: (academy_id, period)
- ``session_attendance_snapshots``: (academy_id, session_id, period)
- ``coach_payout_snapshots``: (academy_id, coach_id, period)

We mark these unique so a duplicated upsert race can't produce two rows
for the same snapshot scope.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0104_reporting_snapshot_indexes"


async def up(db: AsyncIOMotorDatabase) -> None:
    await db.academy_revenue_snapshots.create_index(
        [("academy_id", 1), ("period", 1)],
        name="academy_revenue_snapshots_natural_key",
        unique=True,
    )
    await db.session_attendance_snapshots.create_index(
        [("academy_id", 1), ("session_id", 1), ("period", 1)],
        name="session_attendance_snapshots_natural_key",
        unique=True,
    )
    await db.session_attendance_snapshots.create_index(
        [("academy_id", 1), ("period", 1)],
        name="session_attendance_snapshots_tenant_period",
    )
    await db.coach_payout_snapshots.create_index(
        [("academy_id", 1), ("coach_id", 1), ("period", 1)],
        name="coach_payout_snapshots_natural_key",
        unique=True,
    )
    await db.coach_payout_snapshots.create_index(
        [("academy_id", 1), ("period", 1)],
        name="coach_payout_snapshots_tenant_period",
    )
