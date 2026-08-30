"""Idempotent boot-time migrations runner.

Discovers ``NNNN_*.py`` modules in this package, sorts by numeric prefix, and
runs any whose ``version`` is not yet recorded in ``v2_migrations``.

Each migration module exports ``version: str`` and an async ``up(db)``.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import os
import pkgutil
import uuid
from datetime import UTC, datetime, timedelta, timezone
from types import ModuleType

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.v2.shared.scheduling import job_lease

log = logging.getLogger(__name__)

REGISTRY_COLLECTION = "v2_migrations"

#: Distributed-lock name guarding boot-time migration runs. Reuses the same
#: Mongo-backed ``job_lease`` the scheduler uses, so exactly one machine runs
#: pending migrations when several boot concurrently (issue #507).
MIGRATIONS_LEASE_NAME = "v2_boot_migrations"

#: Generous TTL: data backfills can be slow. If the holder crashes mid-run the
#: lease expires and the next booting machine resumes the (idempotent)
#: migrations from the registry.
MIGRATIONS_LEASE_TTL = timedelta(minutes=15)


def _discover_migrations() -> list[ModuleType]:
    package_name = __package__ or "backend.v2.migrations"
    package = importlib.import_module(package_name)
    discovered: list[tuple[str, str]] = []
    for _finder, name, _ispkg in pkgutil.iter_modules(package.__path__):
        if name == "runner" or name.startswith("_"):
            continue
        if not name[:4].isdigit():
            continue
        discovered.append((name[:4], f"{package_name}.{name}"))

    discovered.sort(key=lambda t: t[0])
    return [importlib.import_module(modname) for _, modname in discovered]


async def _record_applied(db: AsyncIOMotorDatabase, version: str) -> None:
    """Record ``version`` as applied.

    Upsert keyed on ``version`` (matching ``run_all_migrations``) so a lost
    race is a no-op instead of a duplicate registry row, and so the unique
    index on ``version`` (migration 0156) can never be violated by the runner.
    """
    await db[REGISTRY_COLLECTION].update_one(
        {"version": version},
        {"$setOnInsert": {"version": version, "applied_at": datetime.now(UTC)}},
        upsert=True,
    )


async def _run_pending_locked(db: AsyncIOMotorDatabase) -> list[str]:
    applied: set[str] = {doc["version"] async for doc in db[REGISTRY_COLLECTION].find({})}

    just_applied: list[str] = []
    for module in _discover_migrations():
        version: str = module.version
        if version in applied:
            continue
        log.info("Applying migration %s", version)
        await module.up(db)
        await _record_applied(db, version)
        just_applied.append(version)
    return just_applied


async def run_pending_migrations(
    db: AsyncIOMotorDatabase,
    *,
    worker_id: str | None = None,
    poll_interval: float = 2.0,
) -> list[str]:
    """Run pending migrations under a distributed lock.

    Returns the list of versions applied by *this* worker. When another
    machine holds the migrations lease, this call waits (polling every
    ``poll_interval`` seconds) until the lease is released or expires, then
    re-reads the registry — so a boot that lost the race still returns only
    after migrations are applied, typically with an empty list.
    """
    worker = worker_id or os.environ.get("FLY_MACHINE_ID") or f"migrations:{uuid.uuid4()}"
    while True:
        async with job_lease(db, MIGRATIONS_LEASE_NAME, MIGRATIONS_LEASE_TTL, worker) as acquired:
            if acquired:
                return await _run_pending_locked(db)
        log.info("Migrations lease held by another machine; waiting %.1fs", poll_interval)
        await asyncio.sleep(poll_interval)


async def run_all_migrations(db: AsyncIOMotorDatabase) -> list[str]:
    """Replay every migration.

    This is for local/dev reset flows that drop collections after boot-time
    migrations have already been recorded. Migrations are expected to be
    idempotent; production boot should continue using run_pending_migrations.
    """
    replayed: list[str] = []
    for module in _discover_migrations():
        version: str = module.version
        log.info("Replaying migration %s", version)
        await module.up(db)
        await db[REGISTRY_COLLECTION].update_one(
            {"version": version},
            {"$setOnInsert": {"version": version, "applied_at": datetime.now(UTC)}},
            upsert=True,
        )
        replayed.append(version)
    return replayed
