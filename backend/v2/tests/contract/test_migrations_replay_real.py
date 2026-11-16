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

# Two full replays: ~25s alone, past the global 120s cap under full-suite load.
pytestmark = pytest.mark.timeout(300)


async def _indexes(db) -> dict[str, dict]:
    return {
        name: await db[name].index_information()
        for name in sorted(await db.list_collection_names())
    }


@pytest.mark.asyncio
async def test_replay_twice_matches_a_fresh_replay(caplog) -> None:
    caplog.set_level(logging.WARNING)
    url = (
        os.environ.get("V2_MONGO_URL") or os.environ.get("MONGO_URL") or "mongodb://127.0.0.1:27017"
    )
    # A loaded mongod (4 xdist workers replaying migrations) can miss a 1.5s ping.
    client: AsyncIOMotorClient = AsyncIOMotorClient(url, serverSelectionTimeoutMS=10_000)
    try:
        await client.admin.command("ping")
    except Exception as exc:
        client.close()
        pytest.skip(f"no reachable mongod at {url}: {exc}")
    db = client[f"zz_replay_{uuid.uuid4().hex[:8]}"]
    try:
        # The first replay onto an empty database IS the fresh replay; snapshot
        # it rather than paying for a third full replay on a second database.
        await run_all_migrations(db)
        fresh = await _indexes(db)
        await run_all_migrations(db)
        assert await _indexes(db) == fresh
    finally:
        await client.drop_database(db.name)
        client.close()
