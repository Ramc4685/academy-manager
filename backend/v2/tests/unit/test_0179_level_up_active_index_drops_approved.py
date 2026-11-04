"""Issue #786: the active-recommendation index must not include ``APPROVED``.

Migration 0176's ``recs_active_unique`` filter listed ``RECOMMENDED``/
``APPROVING``/``REJECTING``/``APPROVED``. The review use case now writes
``COMPLETED`` on approve (never ``APPROVED``) and
``ACTIVE_LEVEL_UP_STATUSES`` no longer counts ``APPROVED`` as active, so this
migration narrows the index to match. This test pins 0179 to the SAME domain
vocabulary the repository reads, so the two cannot drift the way #657's
dormant validator did.
"""

from __future__ import annotations

import importlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.v2.contexts.student_progress.domain.models import ACTIVE_LEVEL_UP_STATUSES
from backend.v2.migrations import runner

MODULE_NAME = "backend.v2.migrations.0179_level_up_active_index_drops_approved"


@pytest.fixture
def migration():
    return importlib.import_module(MODULE_NAME)


def _mock_db() -> MagicMock:
    db = MagicMock()
    collection = MagicMock()
    collection.drop_index = AsyncMock(return_value=None)
    collection.create_index = AsyncMock(return_value="recs_active_unique")
    db.__getitem__.return_value = collection
    return db


def test_migration_is_discovered_by_the_runner(migration) -> None:
    assert MODULE_NAME in {module.__name__ for module in runner._discover_migrations()}
    assert migration.version == MODULE_NAME.rsplit(".", 1)[-1]


@pytest.mark.asyncio
async def test_active_unique_index_drops_approved_and_matches_the_domain_vocabulary(
    migration,
) -> None:
    db = _mock_db()

    await migration.up(db)

    recs = db["level_up_recommendations"]
    recs.drop_index.assert_awaited_once_with("recs_active_unique")
    _keys, kwargs = recs.create_index.await_args
    assert kwargs["unique"] is True
    assert kwargs["name"] == "recs_active_unique"
    statuses = set(kwargs["partialFilterExpression"]["status"]["$in"])
    assert statuses == ACTIVE_LEVEL_UP_STATUSES
    assert "APPROVED" not in statuses


@pytest.mark.asyncio
async def test_missing_index_and_collection_are_tolerated(migration) -> None:
    """A fresh database, or one that has not run 0176 yet, has neither the
    index nor (on a very fresh one) the collection — the rebuild must not be
    fatal either way."""
    from pymongo.errors import OperationFailure

    db = _mock_db()
    recs = db["level_up_recommendations"]
    recs.drop_index.side_effect = OperationFailure("ns not found", code=26)

    await migration.up(db)

    recs.create_index.assert_awaited_once()
