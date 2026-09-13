"""Issue #619: ``voided`` becomes a legal ``ledger_payments.status`` at rest.

Migration 0132 pinned this collection's status to a five-value enum. Adding a
sixth value in ``domain/ledger.py`` alone would ship a feature that works in
every test (mongomock enforces no validator) and fails in production with
``schemaRulesNotSatisfied`` on the first void — the #657 failure mode exactly.

These tests pin the migration's enum to the SAME source the application reads,
so the two cannot drift, and pin the parts of 0132's validator that a
``collMod`` would otherwise silently drop.
"""

from __future__ import annotations

import importlib
import typing
from unittest.mock import AsyncMock, MagicMock

import pytest
from pymongo.errors import OperationFailure

from backend.v2.contexts.billing.domain.ledger import LedgerPaymentStatus
from backend.v2.migrations import runner

MODULE_NAME = "backend.v2.migrations.0177_ledger_payment_voided_state"

DOMAIN_STATUSES = set(typing.get_args(LedgerPaymentStatus))


@pytest.fixture
def migration():
    return importlib.import_module(MODULE_NAME)


def _mock_db() -> MagicMock:
    db = MagicMock()
    db.command = AsyncMock(return_value={"ok": 1})
    collection = MagicMock()
    collection.create_index = AsyncMock()
    db.__getitem__ = MagicMock(return_value=collection)
    return db


def test_migration_is_discovered_by_the_runner(migration) -> None:
    assert MODULE_NAME in {module.__name__ for module in runner._discover_migrations()}
    assert migration.version == MODULE_NAME.rsplit(".", 1)[-1]


@pytest.mark.asyncio
async def test_collmod_enum_is_the_domain_payment_vocabulary(migration) -> None:
    db = _mock_db()

    await migration.up(db)

    command = db.command.await_args.args[0]
    assert command["collMod"] == "ledger_payments"
    enum = command["validator"]["$jsonSchema"]["properties"]["status"]["enum"]
    assert set(enum) == DOMAIN_STATUSES
    assert "voided" in enum
    # Sorted, so a re-run submits a byte-identical validator.
    assert enum == sorted(DOMAIN_STATUSES)


@pytest.mark.asyncio
async def test_validation_is_moderate_so_existing_documents_survive(migration) -> None:
    db = _mock_db()

    await migration.up(db)

    command = db.command.await_args.args[0]
    assert command["validationLevel"] == "moderate"
    assert command["validationAction"] == "error"


@pytest.mark.asyncio
async def test_keeps_the_rest_of_the_0132_ledger_payments_validator(migration) -> None:
    """collMod REPLACES the validator; dropping 0132's required keys while
    widening the enum would retire the tenant-scoping guard on every insert."""
    db = _mock_db()

    await migration.up(db)

    schema = db.command.await_args.args[0]["validator"]["$jsonSchema"]
    assert set(schema["required"]) == {
        "payment_id",
        "academy_id",
        "parent_id",
        "amount_cents",
        "unapplied_amount_cents",
        "currency",
        "status",
        "created_at",
        "updated_at",
    }
    assert schema["properties"]["academy_id"] == {"bsonType": "string"}


@pytest.mark.asyncio
async def test_builds_the_status_index_the_new_filters_read(migration) -> None:
    db = _mock_db()

    await migration.up(db)

    create_index = db["ledger_payments"].create_index
    assert create_index.await_count == 1
    keys = create_index.await_args.args[0]
    assert keys == [("academy_id", 1), ("status", 1), ("created_at", -1)]


@pytest.mark.asyncio
async def test_missing_collection_is_not_a_boot_failure(migration) -> None:
    db = _mock_db()
    db.command = AsyncMock(side_effect=OperationFailure("ns does not exist", 26))
    db.create_collection = AsyncMock()

    await migration.up(db)

    assert db.create_collection.await_count == 1
    # The index still has to be built on the collection it just created.
    assert db["ledger_payments"].create_index.await_count == 1
