"""Issue #548: the claim statuses are admitted by the collection, not just the code.

The review claim writes ``APPROVING``/``REJECTING`` and a ``claimed_at``
stamp. ``level_up_recommendations`` carries a ``$jsonSchema`` status enum
(migration 0133) and a partial unique index whose filter lists the live
statuses (migration 0122); a value neither of them knows about is either a
write error or — worse — silently outside the uniqueness guarantee. These
tests pin migration 0176 to the SAME domain vocabulary the repository reads,
so the two cannot drift the way #657's dormant validator did.
"""

from __future__ import annotations

import importlib
from typing import get_args
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.v2.contexts.student_progress.domain.models import (
    ACTIVE_LEVEL_UP_STATUSES,
    CLAIMABLE_LEVEL_UP_STATUSES,
    LevelUpStatus,
)
from backend.v2.migrations import runner

MODULE_NAME = "backend.v2.migrations.0176_level_up_claim_statuses"


@pytest.fixture
def migration():
    return importlib.import_module(MODULE_NAME)


def _mock_db() -> MagicMock:
    db = MagicMock()
    db.command = AsyncMock(return_value={"ok": 1})
    collection = MagicMock()
    collection.drop_index = AsyncMock(return_value=None)
    collection.create_index = AsyncMock(return_value="recs_active_unique")
    db.__getitem__.return_value = collection
    return db


def test_migration_is_discovered_by_the_runner(migration) -> None:
    assert MODULE_NAME in {module.__name__ for module in runner._discover_migrations()}
    assert migration.version == MODULE_NAME.rsplit(".", 1)[-1]


@pytest.mark.asyncio
async def test_collmod_enum_is_the_domain_vocabulary(migration) -> None:
    db = _mock_db()

    await migration.up(db)

    command = db.command.await_args.args[0]
    assert command["collMod"] == "level_up_recommendations"
    assert command["validationLevel"] == "moderate"
    status = command["validator"]["$jsonSchema"]["properties"]["status"]
    assert set(status["enum"]) == set(get_args(LevelUpStatus))
    # Sorted, so a re-run submits a byte-identical validator and `collMod`
    # is a genuine no-op rather than a rewrite.
    assert status["enum"] == sorted(get_args(LevelUpStatus))


@pytest.mark.asyncio
async def test_enum_admits_the_claim_statuses(migration) -> None:
    """The claim CAS writes these. Leaving them out would turn every review
    into a write error — #657's failure mode, reproduced by the migration
    that is meant to prevent it."""
    db = _mock_db()

    await migration.up(db)

    status = db.command.await_args.args[0]["validator"]["$jsonSchema"]["properties"]["status"]
    assert CLAIMABLE_LEVEL_UP_STATUSES <= set(status["enum"])


@pytest.mark.asyncio
async def test_validator_restates_0133s_required_fields_and_adds_claimed_at(migration) -> None:
    """collMod replaces the validator wholesale: anything 0133 required and
    this one omits is a guard silently retired."""
    db = _mock_db()

    await migration.up(db)

    schema = db.command.await_args.args[0]["validator"]["$jsonSchema"]
    assert schema["required"] == [
        "rec_id",
        "academy_id",
        "student_id",
        "from_level_id",
        "to_level_id",
        "program_id",
        "status",
        "recommended_by",
        "recommended_at",
    ]
    assert schema["properties"]["claimed_at"] == {"bsonType": ["date", "null"]}


@pytest.mark.asyncio
async def test_active_unique_index_is_rebuilt_over_the_claimed_statuses(migration) -> None:
    """A claimed row must stay inside the partial unique index.

    Otherwise the claim window is exactly the window in which a second live
    recommendation for the same student and level could be inserted.
    """
    db = _mock_db()

    await migration.up(db)

    recs = db["level_up_recommendations"]
    recs.drop_index.assert_awaited_once_with("recs_active_unique")
    _keys, kwargs = recs.create_index.await_args
    assert kwargs["unique"] is True
    assert kwargs["name"] == "recs_active_unique"
    assert set(kwargs["partialFilterExpression"]["status"]["$in"]) == ACTIVE_LEVEL_UP_STATUSES
