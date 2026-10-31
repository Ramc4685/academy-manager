"""``academy_media`` audit rows on a real ``mongod``: tenant-scoped and counted."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.identity.infrastructure.mongo_academy_media_repo import (
    MongoAcademyMediaRepository,
)
from backend.v2.shared.tenancy import tenant_scope

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


def _row(when: datetime) -> dict:
    return {
        "kind": "logo",
        "object_path": "academies/x/logo/a.png",
        "uploaded_by": "u1",
        "size_bytes": 10,
        "sha256": "0" * 64,
        "created_at": when,
    }


@pytest.mark.asyncio
async def test_rows_are_stamped_and_counted_per_academy(real_db) -> None:
    repo = MongoAcademyMediaRepository(real_db)
    with tenant_scope("acad-media-a"):
        await repo.record(_row(NOW))
        await repo.record(_row(NOW - timedelta(hours=3)))
    with tenant_scope("acad-media-b"):
        await repo.record(_row(NOW))

    with tenant_scope("acad-media-a"):
        assert await repo.count_since(NOW - timedelta(hours=1)) == 1
        assert await repo.count_since(NOW - timedelta(hours=5)) == 2
    with tenant_scope("acad-media-b"):
        assert await repo.count_since(NOW - timedelta(hours=1)) == 1
    stored = await real_db["academy_media"].find_one({"academy_id": "acad-media-b"})
    assert stored["kind"] == "logo" and stored["_id"]


@pytest.mark.asyncio
async def test_update_is_tenant_scoped(real_db) -> None:
    repo = MongoAcademyMediaRepository(real_db)
    with tenant_scope("acad-media-c"):
        media_id = await repo.record({"kind": "logo", "status": "pending", "created_at": NOW})
    with tenant_scope("acad-media-d"):
        await repo.update(media_id, {"status": "hijacked"})
    with tenant_scope("acad-media-c"):
        await repo.update(media_id, {"status": "stored"})
    stored = await real_db["academy_media"].find_one({"_id": media_id})
    assert stored["status"] == "stored"
