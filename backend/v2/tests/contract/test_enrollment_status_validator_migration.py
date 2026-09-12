"""Issue #642: the enrollment status vocabulary becomes a rule at rest.

``update_status(status: str)`` accepts any string and ``enrollments.status``
has never been enum-constrained (migration 0132 leaves it an unconstrained
``{"bsonType": "string"}``, and 0171 explicitly notes it stays that way). A
typo, or a reader inventing a fourth spelling of "gone", lands in the
collection and is then invisible to every ``$in`` filter that lists the real
statuses — silently, with the row simply missing from the roster.

These tests pin the validator to the SAME source the application reads from,
so the two can never drift: the enum is the domain's
``STORED_ENROLLMENT_STATUSES``, not a second hand-typed list.
"""

from __future__ import annotations

import importlib
from unittest.mock import AsyncMock, MagicMock

import pytest
from pymongo.errors import OperationFailure

from backend.v2.contexts.enrollment.domain.models import (
    ENROLLMENT_STATUSES,
    STORED_ENROLLMENT_STATUSES,
    TRANSIENT_DELETING_STATUS,
)
from backend.v2.migrations import runner

MODULE_NAME = "backend.v2.migrations.0175_enrollment_status_enum_validator"


@pytest.fixture
def migration():
    return importlib.import_module(MODULE_NAME)


def _mock_db() -> MagicMock:
    db = MagicMock()
    db.command = AsyncMock(return_value={"ok": 1})
    return db


def test_migration_is_discovered_by_the_runner(migration) -> None:
    assert MODULE_NAME in {module.__name__ for module in runner._discover_migrations()}
    assert migration.version == MODULE_NAME.rsplit(".", 1)[-1]


@pytest.mark.asyncio
async def test_collmod_enum_is_the_domain_vocabulary(migration) -> None:
    db = _mock_db()

    await migration.up(db)

    command = db.command.await_args.args[0]
    assert command["collMod"] == "enrollments"
    status = command["validator"]["$jsonSchema"]["properties"]["status"]
    assert set(status["enum"]) == STORED_ENROLLMENT_STATUSES
    # Sorted, so a re-run produces a byte-identical validator and `collMod`
    # is a genuine no-op rather than a rewrite.
    assert status["enum"] == sorted(STORED_ENROLLMENT_STATUSES)


@pytest.mark.asyncio
async def test_enum_admits_the_transient_delete_sentinel(migration) -> None:
    """``delete_if_status`` CAS-stamps ``__deleting__`` on the row before
    removing it. Leaving it out of the enum would make every hard delete
    raise a write error instead — the failure mode #657 hit with a dormant
    validator, reproduced here as a test rather than in production."""
    db = _mock_db()

    await migration.up(db)

    enum = db.command.await_args.args[0]["validator"]["$jsonSchema"]["properties"]["status"]["enum"]
    assert TRANSIENT_DELETING_STATUS in enum
    assert ENROLLMENT_STATUSES <= set(enum)


@pytest.mark.asyncio
async def test_legacy_spellings_stay_valid(migration) -> None:
    """Pre-#699 rows still say "withdrawn"/"cancelled" and pre-#697 rows say
    "paused". The enum must not evict rows the dual-read code still reads."""
    db = _mock_db()

    await migration.up(db)

    enum = db.command.await_args.args[0]["validator"]["$jsonSchema"]["properties"]["status"]["enum"]
    for legacy in ("withdrawn", "cancelled", "paused"):
        assert legacy in enum


@pytest.mark.asyncio
async def test_validation_is_moderate_so_existing_documents_survive(migration) -> None:
    """Production holds rows this enum may not cover (and rows with no
    ``status`` at all, which the readers treat as ``active``). ``moderate``
    validates inserts and updates to already-valid documents only, so the
    migration cannot brick writes to a legacy row."""
    db = _mock_db()

    await migration.up(db)

    command = db.command.await_args.args[0]
    assert command["validationLevel"] == "moderate"
    assert command["validationAction"] == "error"


@pytest.mark.asyncio
async def test_keeps_the_rest_of_the_0132_enrollments_validator(migration) -> None:
    """This is a collMod, which REPLACES the validator wholesale. Dropping
    0132's required keys while adding the enum would quietly retire the
    tenant-scoping guard on every insert."""
    db = _mock_db()

    await migration.up(db)

    schema = db.command.await_args.args[0]["validator"]["$jsonSchema"]
    assert set(schema["required"]) == {
        "academy_id",
        "enrollment_id",
        "student_id",
        "session_id",
        "status",
    }
    assert schema["properties"]["academy_id"] == {"bsonType": "string"}


@pytest.mark.asyncio
async def test_missing_collection_is_not_a_boot_failure(migration) -> None:
    """A fresh database has no ``enrollments`` collection yet; collMod then
    fails with code 26. Migrations run at boot, so this must be survivable."""
    db = _mock_db()
    db.command = AsyncMock(side_effect=OperationFailure("ns does not exist", 26))
    db.create_collection = AsyncMock()

    await migration.up(db)

    assert db.create_collection.await_count == 1
