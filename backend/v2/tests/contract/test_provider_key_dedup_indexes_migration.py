"""#526: the revenue dedup's provider-key lookups need index support.

The reports dashboard looks ledger payments up by the provider keys the
period's legacy rows carry, and the revenue CSV export runs batched ``$or``
queries over the same six fields. An ``$or`` whose branches are not all
indexed degenerates to a collection scan, so these tests pin that every one
of the six is now covered on both collections.
"""

from __future__ import annotations

import importlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.v2.contexts.billing.infrastructure.cash_received import _PROVIDER_KEY_FIELDS
from backend.v2.migrations import runner

MODULE_NAME = "backend.v2.migrations.0178_provider_key_dedup_indexes"


@pytest.fixture
def migration():
    return importlib.import_module(MODULE_NAME)


@pytest.mark.asyncio
async def test_migration_is_discovered_by_the_runner(migration) -> None:
    assert MODULE_NAME in {module.__name__ for module in runner._discover_migrations()}
    assert migration.version == MODULE_NAME.rsplit(".", 1)[-1]


@pytest.mark.asyncio
async def test_creates_the_missing_provider_key_indexes(db, migration) -> None:
    await migration.up(db)

    for collection, field, name in migration.INDEXES:
        index = (await db[collection].index_information())[name]
        assert index["key"] == [("academy_id", 1), (field, 1)]
        assert index["partialFilterExpression"] == {field: {"$type": "string"}}
        assert index.get("unique") is not True


@pytest.mark.asyncio
async def test_running_it_twice_is_a_no_op(db, migration) -> None:
    await migration.up(db)
    before = await db["payments"].index_information()

    await migration.up(db)

    assert await db["payments"].index_information() == before


@pytest.mark.asyncio
async def test_every_dedup_provider_key_ends_up_indexed_on_both_collections(db, migration) -> None:
    """0030/0091/0126/0128/0130/0173 cover the rest; together with this
    migration no ``$or`` branch is left without an index."""
    earlier = (
        "0030_billing_indexes",
        "0091_billing_ledger_indexes",
        "0126_stripe_webhook_event_pipeline_indexes",
        "0128_ledger_payments_storage",
        "0130_stripe_subscription_ledger_indexes",
        "0173_ledger_payment_intent_unique_index",
    )
    for name in earlier:
        await importlib.import_module(f"backend.v2.migrations.{name}").up(db)
    await migration.up(db)

    for collection in ("payments", "ledger_payments"):
        indexed = {
            tuple(key for key, _direction in index["key"])
            for index in (await db[collection].index_information()).values()
        }
        for field in _PROVIDER_KEY_FIELDS:
            assert ("academy_id", field) in indexed, f"{collection}.{field} unindexed"


@pytest.mark.asyncio
async def test_builds_every_index_in_the_background(migration) -> None:
    collection = MagicMock()
    collection.create_index = AsyncMock()
    db = MagicMock()
    db.__getitem__ = MagicMock(return_value=collection)

    await migration.up(db)

    assert collection.create_index.await_count == len(migration.INDEXES)
    for call in collection.create_index.await_args_list:
        assert call.kwargs["background"] is True
