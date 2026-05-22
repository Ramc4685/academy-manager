"""Migration smoke tests against legacy-shaped local data.

The v2 app can be booted against the existing academy database during the
strangler migration. Legacy collections may not have v2 synthetic ID fields
yet, so v2 unique indexes must ignore missing/null v2 IDs.
"""

from __future__ import annotations

import importlib

import pytest


class _MongoIndexOptionRejectingCollection:
    def __init__(self) -> None:
        self.calls: list[tuple[object, dict[str, object]]] = []

    async def create_index(self, keys, **kwargs):
        self.calls.append((keys, kwargs))
        if kwargs.get("sparse") and "partialFilterExpression" in kwargs:
            raise AssertionError("MongoDB rejects sparse with partialFilterExpression")
        return kwargs.get("name", "idx")


class _MongoIndexOptionRejectingDb:
    def __init__(self) -> None:
        self.collections: dict[str, _MongoIndexOptionRejectingCollection] = {}

    def __getitem__(self, name: str) -> _MongoIndexOptionRejectingCollection:
        return self.collections.setdefault(name, _MongoIndexOptionRejectingCollection())


@pytest.mark.asyncio
async def test_enrollment_migration_tolerates_legacy_rows_without_v2_ids(db) -> None:
    await db["sessions"].insert_many(
        [
            {"academy_id": "legacy-academy", "name": "Beginner", "session_id": None},
            {"academy_id": "legacy-academy", "name": "Intermediate"},
        ]
    )
    await db["enrollments"].insert_many(
        [
            {"academy_id": "legacy-academy", "student_id": "legacy-student"},
            {"academy_id": "legacy-academy", "student_id": "legacy-student-2"},
        ]
    )
    await db["students"].insert_many(
        [
            {"academy_id": "legacy-academy", "full_name": "A"},
            {"academy_id": "legacy-academy", "full_name": "B", "student_id": None},
        ]
    )

    migration = importlib.import_module("backend.v2.migrations.0010_enrollment_indexes")
    await migration.up(db)

    assert await db["sessions"].count_documents({"session_id": {"$exists": True, "$eq": None}}) == 0
    assert await db["students"].count_documents({"student_id": {"$exists": True, "$eq": None}}) == 0


@pytest.mark.asyncio
async def test_attendance_migration_tolerates_legacy_rows_without_v2_ids(db) -> None:
    await db["attendance"].insert_many(
        [
            {
                "academy_id": "legacy-academy",
                "session_id": "s1",
                "student_id": "st1",
                "attendance_id": None,
            },
            {
                "academy_id": "legacy-academy",
                "session_id": "s1",
                "student_id": "st2",
            },
        ]
    )

    migration = importlib.import_module("backend.v2.migrations.0020_coaching_attendance_indexes")
    await migration.up(db)

    assert (
        await db["attendance"].count_documents({"attendance_id": {"$exists": True, "$eq": None}})
        == 0
    )


@pytest.mark.asyncio
async def test_admin_student_directory_migration_declares_attendance_lookup_index(db) -> None:
    migration = importlib.import_module(
        "backend.v2.migrations.0070_admin_student_directory_indexes"
    )
    await migration.up(db)

    indexes = await db["attendance"].index_information()
    assert any(
        info["key"] == [("academy_id", 1), ("student_id", 1), ("marked_at", -1)]
        for info in indexes.values()
    )


@pytest.mark.asyncio
async def test_billing_migration_accepts_existing_stripe_event_id_index(db) -> None:
    await db["stripe_webhook_events"].create_index("event_id", unique=True)

    migration = importlib.import_module("backend.v2.migrations.0030_billing_indexes")
    await migration.up(db)

    indexes = await db["stripe_webhook_events"].index_information()
    assert any(info["key"] == [("event_id", 1)] for info in indexes.values())


@pytest.mark.asyncio
async def test_message_campaign_migration_uses_valid_mongo_index_options() -> None:
    migration = importlib.import_module("backend.v2.migrations.0101_message_campaign_indexes")
    fake_db = _MongoIndexOptionRejectingDb()

    await migration.up(fake_db)  # type: ignore[arg-type]

    deliveries = fake_db.collections["message_deliveries"]
    provider_index = next(
        kwargs
        for _keys, kwargs in deliveries.calls
        if kwargs.get("name") == "message_deliveries_provider_message_id_unique"
    )
    assert provider_index["partialFilterExpression"] == {"provider_message_id": {"$type": "string"}}
    assert "sparse" not in provider_index
