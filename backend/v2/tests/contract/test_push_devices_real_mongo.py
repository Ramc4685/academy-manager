"""``push_devices`` on a real ``mongod`` with migration 0215 applied (mobile M2).

Pins the store semantics the push channel will rely on: one row per token,
idempotent re-registration, a token moving to whoever registers it last (also
across academies), and deletes that only the holder in its own academy can do.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.communications.domain.push_device import PushDevice
from backend.v2.contexts.communications.infrastructure.mongo_push_device_repo import (
    MongoPushDeviceRepository,
)
from backend.v2.shared.tenancy import tenant_scope

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
T1 = T0 + timedelta(days=1)
TOKEN = "fcm-token-1"


def _device(user_id: str, at: datetime, token: str = TOKEN, **kw) -> PushDevice:
    return PushDevice(
        user_id=user_id,
        token=token,
        platform=kw.get("platform", "ios"),
        app_version=kw.get("app_version", "1.0.0"),
        created_at=at,
        last_seen_at=at,
    )


async def test_reregistering_is_idempotent_and_refreshes_last_seen(real_db) -> None:
    repo = MongoPushDeviceRepository(real_db)
    with tenant_scope("acad-push-a"):
        await repo.register(_device("u1", T0))
        stored = await repo.register(_device("u1", T1, app_version="1.1.0"))

    assert await real_db["push_devices"].count_documents({}) == 1
    assert stored.created_at.replace(tzinfo=UTC) == T0
    assert stored.last_seen_at.replace(tzinfo=UTC) == T1
    assert stored.app_version == "1.1.0"
    row = await real_db["push_devices"].find_one({"token": TOKEN})
    assert row["academy_id"] == "acad-push-a" and row["user_id"] == "u1"


async def test_token_moves_to_the_user_who_registers_it_last(real_db) -> None:
    repo = MongoPushDeviceRepository(real_db)
    with tenant_scope("acad-push-a"):
        await repo.register(_device("mom", T0))
        await repo.register(_device("dad", T1, platform="android"))

    rows = await real_db["push_devices"].find({"token": TOKEN}).to_list(None)
    assert [(r["user_id"], r["platform"]) for r in rows] == [("dad", "android")]


async def test_token_moves_across_academies(real_db) -> None:
    repo = MongoPushDeviceRepository(real_db)
    with tenant_scope("acad-push-a"):
        await repo.register(_device("u1", T0))
    with tenant_scope("acad-push-b"):
        await repo.register(_device("u2", T1))

    rows = await real_db["push_devices"].find({"token": TOKEN}).to_list(None)
    assert [(r["academy_id"], r["user_id"]) for r in rows] == [("acad-push-b", "u2")]


async def test_delete_only_by_the_holder_in_its_academy(real_db) -> None:
    repo = MongoPushDeviceRepository(real_db)
    with tenant_scope("acad-push-a"):
        await repo.register(_device("u1", T0))
        await repo.delete(user_id="someone-else", token=TOKEN)
    with tenant_scope("acad-push-b"):
        await repo.delete(user_id="u1", token=TOKEN)
    assert await real_db["push_devices"].count_documents({"token": TOKEN}) == 1

    with tenant_scope("acad-push-a"):
        await repo.delete(user_id="u1", token=TOKEN)
        await repo.delete(user_id="u1", token="never-registered")  # no-op, no error
    assert await real_db["push_devices"].count_documents({}) == 0


async def test_migration_makes_token_unique(real_db) -> None:
    row = {"token": "dup", "user_id": "u1", "academy_id": "a"}
    await real_db["push_devices"].insert_one(dict(row))
    with pytest.raises(DuplicateKeyError):
        await real_db["push_devices"].insert_one({**row, "user_id": "u2", "academy_id": "b"})
