"""Idempotent boot-time migrations runner.

Discovers ``NNNN_*.py`` modules in this package, sorts by numeric prefix, and
runs any whose ``version`` is not yet recorded in ``v2_migrations``.

Each migration module exports ``version: str`` and an async ``up(db)``.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase

log = logging.getLogger(__name__)

REGISTRY_COLLECTION = "v2_migrations"


async def run_pending_migrations(db: AsyncIOMotorDatabase) -> list[str]:
    """Run pending migrations. Returns the list of versions applied."""
    applied: set[str] = {
        doc["version"] async for doc in db[REGISTRY_COLLECTION].find({})
    }

    package_name = __package__ or "backend.v2.migrations"
    package = importlib.import_module(package_name)
    discovered: list[tuple[str, str]] = []
    for finder, name, _ispkg in pkgutil.iter_modules(package.__path__):
        if name == "runner" or name.startswith("_"):
            continue
        if not name[:4].isdigit():
            continue
        discovered.append((name[:4], f"{package_name}.{name}"))

    discovered.sort(key=lambda t: t[0])
    just_applied: list[str] = []
    for _, modname in discovered:
        module = importlib.import_module(modname)
        version: str = getattr(module, "version")
        if version in applied:
            continue
        log.info("Applying migration %s", version)
        await module.up(db)
        await db[REGISTRY_COLLECTION].insert_one(
            {"version": version, "applied_at": datetime.now(timezone.utc)}
        )
        just_applied.append(version)
    return just_applied
