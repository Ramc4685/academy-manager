"""Contract-test fixtures.

``db`` is a real MongoDB database when ``CONTRACT_TESTS_MONGO_URL`` is set
(CI sets it against the native mongod 8.0, the production major), so repo
tests exercise the real query planner and index semantics. Without it the
fixture falls back to ``mongomock-motor`` for a fast local run.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def db() -> AsyncIterator[object]:
    url = os.environ.get("CONTRACT_TESTS_MONGO_URL")
    if url:
        from motor.motor_asyncio import AsyncIOMotorClient

        client = AsyncIOMotorClient(url, serverSelectionTimeoutMS=5000)
        # Unique name per test so xdist workers never share state.
        name = f"contract_{uuid.uuid4().hex}"
        try:
            yield client[name]
        finally:
            await client.drop_database(name)
            client.close()
        return
    try:
        from mongomock_motor import AsyncMongoMockClient  # type: ignore[import-not-found]
    except ImportError:  # pragma: no cover
        import pytest

        pytest.skip("mongomock-motor not installed")
    client = AsyncMongoMockClient()
    yield client["test_db"]


@pytest_asyncio.fixture
async def acad():
    """Activate tenant ContextVar for the test. Sync set/reset works fine
    inside the async test body; pytest-asyncio's teardown across event
    loops trips up the context-manager form."""
    from backend.v2.shared.tenancy.context import _current as _tv

    token = _tv.set("test-academy")
    try:
        yield "test-academy"
    finally:
        try:
            _tv.reset(token)
        except (ValueError, LookupError):
            # The reset can fail if pytest-asyncio finalises us from a
            # different Context; that's harmless — the next test sets its
            # own value.
            pass


@pytest_asyncio.fixture
async def other_acad():
    """Used to assert tenant isolation."""
    from backend.v2.shared.tenancy.context import _current as _tv

    token = _tv.set("other-academy")
    try:
        yield "other-academy"
    finally:
        try:
            _tv.reset(token)
        except (ValueError, LookupError):
            pass


# ---------------------------------------------------------------------------
# Real MongoDB, migrations applied.
#
# mongomock does not enforce what the money paths lean on under concurrency:
# partial unique indexes, conditional updates racing each other, and the
# launch validators (0132). ``real_db`` is a throwaway database on a real
# ``mongod`` (the CI backend job's ``mongo:8`` service; locally whatever
# listens on 27017) with every migration replayed ONCE per session, so the
# production indexes and validators exist. Each test starts from empty
# collections (indexes and validators kept). Skipped, not failed, when no
# ``mongod`` is reachable, exactly like test_partial_index_planner_usability.
# ---------------------------------------------------------------------------


def _real_mongo_url() -> str:
    import os

    return (
        os.environ.get("V2_MONGO_URL") or os.environ.get("MONGO_URL") or "mongodb://127.0.0.1:27017"
    )


@pytest.fixture(scope="session")
def _real_mongo_database() -> Iterator[tuple[str, str]]:
    import asyncio
    import os
    import uuid

    from motor.motor_asyncio import AsyncIOMotorClient

    from backend.v2.migrations import runner

    url = _real_mongo_url()
    name = f"zz_contract_real_{os.getpid()}_{uuid.uuid4().hex[:8]}"

    async def _setup() -> str | None:
        client: AsyncIOMotorClient[Any] = AsyncIOMotorClient(url, serverSelectionTimeoutMS=1500)
        try:
            try:
                await client.admin.command("ping")
            except Exception as exc:  # any failure means "no mongod here"
                return f"no reachable mongod at {url}: {exc}"
            database = client[name]
            for module in runner._discover_migrations():
                await module.up(database)
            return None
        finally:
            client.close()

    async def _teardown() -> None:
        client: AsyncIOMotorClient[Any] = AsyncIOMotorClient(url, serverSelectionTimeoutMS=1500)
        try:
            await client.drop_database(name)
        finally:
            client.close()

    skip_reason = asyncio.run(_setup())
    if skip_reason is not None:
        pytest.skip(skip_reason)
    try:
        yield url, name
    finally:
        asyncio.run(_teardown())


@pytest_asyncio.fixture
async def real_db(_real_mongo_database: tuple[str, str]) -> AsyncIterator[Any]:
    from motor.motor_asyncio import AsyncIOMotorClient

    url, name = _real_mongo_database
    client: AsyncIOMotorClient[Any] = AsyncIOMotorClient(url, serverSelectionTimeoutMS=1500)
    database = client[name]
    for collection in await database.list_collection_names():
        if not collection.startswith("system."):
            await database[collection].delete_many({})
    try:
        yield database
    finally:
        client.close()
