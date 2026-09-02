"""The shared tenant-timezone reader must report "unset" honestly.

Every other academy reader in the repo substitutes ``"UTC"`` for a missing
timezone. That substitution is the bug: it is indistinguishable from a tenant
that genuinely runs on UTC, so writes cannot fail closed and displays cannot
show a visible fallback. This lookup returns ``None`` instead.
"""

from __future__ import annotations

import pytest

from backend.v2.shared.time import academy_timezone_lookup


@pytest.fixture
def db():
    mongomock_motor = pytest.importorskip("mongomock_motor")
    return mongomock_motor.AsyncMongoMockClient()["test_db"]


@pytest.mark.asyncio
async def test_returns_the_stored_timezone(db) -> None:
    await db["academies"].insert_one(
        {"academy_id": "acad-1", "timezone": "America/Chicago"},
    )

    assert await academy_timezone_lookup(db)("acad-1") == "America/Chicago"


@pytest.mark.asyncio
async def test_missing_timezone_field_is_none_not_utc(db) -> None:
    await db["academies"].insert_one({"academy_id": "acad-1", "display_name": "BLNO"})

    assert await academy_timezone_lookup(db)("acad-1") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("stored", ["", "   "])
async def test_blank_timezone_is_none(db, stored: str) -> None:
    await db["academies"].insert_one({"academy_id": "acad-1", "timezone": stored})

    assert await academy_timezone_lookup(db)("acad-1") is None


@pytest.mark.asyncio
async def test_unknown_academy_is_none(db) -> None:
    assert await academy_timezone_lookup(db)("nope") is None
