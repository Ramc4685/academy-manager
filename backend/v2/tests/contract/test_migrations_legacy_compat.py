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
        self.updates: list[tuple[object, object]] = []

    async def create_index(self, keys, **kwargs):
        self.calls.append((keys, kwargs))
        if kwargs.get("sparse") and "partialFilterExpression" in kwargs:
            raise AssertionError("MongoDB rejects sparse with partialFilterExpression")
        return kwargs.get("name", "idx")

    async def update_many(self, filter_, update):
        self.updates.append((filter_, update))

    async def index_information(self):
        return {}


class _MongoIndexOptionRejectingDb:
    def __init__(self) -> None:
        self.collections: dict[str, _MongoIndexOptionRejectingCollection] = {}

    def __getitem__(self, name: str) -> _MongoIndexOptionRejectingCollection:
        return self.collections.setdefault(name, _MongoIndexOptionRejectingCollection())


class _LaunchMigrationDb(_MongoIndexOptionRejectingDb):
    def __init__(self) -> None:
        super().__init__()
        self.commands: list[dict[str, object]] = []

    async def command(self, command: dict[str, object]) -> dict[str, int]:
        self.commands.append(command)
        return {"ok": 1}

    async def create_collection(self, *_args, **_kwargs):  # pragma: no cover - fallback aid
        raise AssertionError("existing collections should use collMod in this test")


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


@pytest.mark.asyncio
async def test_legacy_payment_retirement_cleanup_moves_user_stripe_customer_and_drops_stale_indexes(
    db,
) -> None:
    await db["users"].insert_one(
        {
            "academy_id": "acad-1",
            "user_id": "parent-1",
            "stripe_customer_id": "cus_123",
        }
    )
    await db["users"].create_index(
        "stripe_customer_id",
        unique=True,
        partialFilterExpression={"stripe_customer_id": {"$type": "string"}},
        name="stripe_customer_unique",
    )
    await db["payments"].create_index(
        [("academy_id", 1), ("ledger_idempotency_key", 1)],
        unique=True,
        partialFilterExpression={"ledger_idempotency_key": {"$type": "string"}},
        name="academy_payment_ledger_idempotency_unique",
    )
    await db["payments"].create_index(
        [("academy_id", 1), ("payment_id", 1)],
        unique=True,
        partialFilterExpression={"payment_id": {"$type": "string"}},
        name="academy_payment_id_unique",
    )
    await db["payments"].create_index(
        [("academy_id", 1), ("stripe_invoice_id", 1)],
        unique=True,
        partialFilterExpression={"stripe_invoice_id": {"$type": "string"}},
        name="academy_stripe_invoice_unique",
    )

    migration = importlib.import_module(
        "backend.v2.migrations.0131_legacy_payment_retirement_cleanup"
    )
    await migration.up(db)

    user = await db["users"].find_one({"user_id": "parent-1"})
    assert user is not None
    assert "stripe_customer_id" not in user
    customer = await db["parent_billing_customers"].find_one(
        {"academy_id": "acad-1", "parent_id": "parent-1"}
    )
    assert customer is not None
    assert customer["stripe_customer_id"] == "cus_123"

    user_indexes = await db["users"].index_information()
    payment_indexes = await db["payments"].index_information()
    assert "stripe_customer_unique" not in user_indexes
    assert "academy_payment_ledger_idempotency_unique" not in payment_indexes
    assert "academy_payment_id_unique" not in payment_indexes
    assert "academy_stripe_invoice_unique" not in payment_indexes


@pytest.mark.asyncio
async def test_launch_indexes_and_validators_migration_declares_required_contracts() -> None:
    migration = importlib.import_module("backend.v2.migrations.0132_launch_indexes_and_validators")
    fake_db = _LaunchMigrationDb()

    await migration.up(fake_db)  # type: ignore[arg-type]

    coach_indexes = {
        kwargs["name"] for _keys, kwargs in fake_db.collections["coach_attendance"].calls
    }
    settings_indexes = {
        kwargs["name"] for _keys, kwargs in fake_db.collections["academy_settings"].calls
    }
    credit_indexes = {
        kwargs["name"] for _keys, kwargs in fake_db.collections["account_credit_ledger"].calls
    }
    validator_collections = {str(command["collMod"]) for command in fake_db.commands}

    assert {
        "coach_attendance_occurrence_coach_unique",
        "coach_attendance_coach_marked_at",
        "coach_attendance_status_marked_at",
    }.issubset(coach_indexes)
    assert {
        "academy_settings_academy_unique",
        "academy_settings_id_unique",
    }.issubset(settings_indexes)
    assert {
        "academy_credit_id_unique",
        "academy_credit_parent_status",
    }.issubset(credit_indexes)
    assert set(migration.VALIDATORS).issubset(validator_collections)


@pytest.mark.asyncio
async def test_launch_validators_migration_is_mongomock_safe(db) -> None:
    """mongomock does not implement collMod validators; the migration should
    still create supported indexes and skip unsupported validator commands.
    """
    migration = importlib.import_module("backend.v2.migrations.0132_launch_indexes_and_validators")

    await migration.up(db)

    coach_indexes = await db["coach_attendance"].index_information()
    settings_indexes = await db["academy_settings"].index_information()
    assert "coach_attendance_occurrence_coach_unique" in coach_indexes
    assert "academy_settings_academy_unique" in settings_indexes


@pytest.mark.asyncio
async def test_broader_validators_and_outbox_migration_declares_required_contracts() -> None:
    migration = importlib.import_module(
        "backend.v2.migrations.0133_broader_validators_and_outbox_retry_lock"
    )
    fake_db = _LaunchMigrationDb()

    await migration.up(fake_db)  # type: ignore[arg-type]

    outbox_indexes = {
        kwargs["name"] for _keys, kwargs in fake_db.collections["outbox_events"].calls
    }
    validator_collections = {str(command["collMod"]) for command in fake_db.commands}
    outbox_updates = fake_db.collections["outbox_events"].updates

    assert {
        "outbox_worker_claim_queue",
        "outbox_status_attempts",
        "outbox_stale_locks",
    }.issubset(outbox_indexes)
    assert set(migration.VALIDATORS).issubset(validator_collections)
    assert len(outbox_updates) == 3


@pytest.mark.asyncio
async def test_broader_validators_and_outbox_migration_is_mongomock_safe(db) -> None:
    migration = importlib.import_module(
        "backend.v2.migrations.0133_broader_validators_and_outbox_retry_lock"
    )
    await db["outbox_events"].insert_many(
        [
            {"event_id": "evt-old-pending", "processed": False, "created_at": "legacy"},
            {"event_id": "evt-old-processed", "processed": True, "created_at": "legacy"},
        ]
    )

    await migration.up(db)

    indexes = await db["outbox_events"].index_information()
    pending = await db["outbox_events"].find_one({"event_id": "evt-old-pending"})
    processed = await db["outbox_events"].find_one({"event_id": "evt-old-processed"})
    assert "outbox_worker_claim_queue" in indexes
    assert "outbox_status_attempts" in indexes
    assert "outbox_stale_locks" in indexes
    assert pending["status"] == "pending"
    assert pending["attempt_count"] == 0
    assert processed["status"] == "processed"
