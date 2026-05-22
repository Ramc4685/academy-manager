"""Indexes for the ``coach_rates`` collection (Wave 4A).

Storage layout:

- ``coach_rates`` (per-academy, per-coach, versioned by effective_from).

Queries:

- ``find_for_coach_at(coach_id, at_time)`` — needs (academy_id, coach_id,
  effective_from desc) + (effective_until) filter.
- Listing all current rates for an academy — uses (academy_id, status,
  effective_from desc).

The collection is tenant-scoped; every read goes through a
``TenantScopedRepository`` that pre-filters by ``academy_id``.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0102_coach_rate_indexes"


async def up(db: AsyncIOMotorDatabase) -> None:
    await db.coach_rates.create_index(
        [("academy_id", 1), ("coach_id", 1), ("effective_from", -1)],
        name="coach_rates_tenant_coach_effective",
    )
    await db.coach_rates.create_index(
        [("academy_id", 1), ("status", 1), ("effective_from", -1)],
        name="coach_rates_tenant_status_effective",
    )
    await db.coach_rates.create_index(
        [("academy_id", 1), ("rate_id", 1)],
        name="coach_rates_id",
        unique=True,
    )
