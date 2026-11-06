"""``run_all_migrations`` must replay onto an already-migrated database.

``local_test_stack.sh seed`` replays every migration after the seed reset. On
a DB that was migrated before, later migrations' redefined indexes used to
collide with earlier ones (Mongo IndexOptionsConflict / IndexKeySpecsConflict).
Real ``mongod`` only; skipped when none is reachable.
"""

from __future__ import annotations

import logging
import os
import uuid

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from backend.v2.migrations.runner import run_all_migrations


async def _indexes(db) -> dict[str, dict]:
    return {
        name: await db[name].index_information()
        for name in sorted(await db.list_collection_names())
    }


@pytest.mark.asyncio
async def test_replay_twice_matches_a_fresh_replay(caplog) -> None:
    caplog.set_level(logging.WARNING)
    url = os.environ.get("V2_MONGO_URL") or os.environ.get("MONGO_URL") or "mongodb://127.0.0.1:27017"
    client: AsyncIOMotorClient = AsyncIOMotorClient(url, serverSelectionTimeoutMS=1500)
    try:
        await client.admin.command("ping")
    except Exception as exc:
        client.close()
        pytest.skip(f"no reachable mongod at {url}: {exc}")
    suffix = uuid.uuid4().hex[:8]
    once, twice = client[f"zz_replay_once_{suffix}"], client[f"zz_replay_twice_{suffix}"]
    try:
        await run_all_migrations(once)
        await run_all_migrations(twice)
        await run_all_migrations(twice)
        assert await _indexes(twice) == await _indexes(once)
    finally:
        await client.drop_database(once.name)
        await client.drop_database(twice.name)
        client.close()
