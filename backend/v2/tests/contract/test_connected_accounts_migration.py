"""Migration smoke test: 0139_connected_accounts (Slice I).

Verifies the migration is idempotent, creates the unique index on academy_id
and a lookup index on stripe_account_id, and enforces one connected account
per academy.
"""

from __future__ import annotations

import importlib

import pytest
from pymongo.errors import DuplicateKeyError


@pytest.fixture
def migration():
    return importlib.import_module("backend.v2.migrations.0139_connected_accounts")


async def test_migration_is_idempotent(db, migration) -> None:
    await migration.up(db)
    await migration.up(db)  # second run must not raise

    indexes = await db["academy_connected_accounts"].index_information()
    assert "academy_connected_accounts_academy_unique" in indexes
    assert "academy_connected_accounts_stripe_account" in indexes


async def test_academy_index_is_unique(db, migration) -> None:
    await migration.up(db)

    indexes = await db["academy_connected_accounts"].index_information()
    assert indexes["academy_connected_accounts_academy_unique"].get("unique") is True


async def test_stripe_account_index_is_unique_and_sparse(db, migration) -> None:
    await migration.up(db)

    indexes = await db["academy_connected_accounts"].index_information()
    stripe_index = indexes["academy_connected_accounts_stripe_account"]
    assert stripe_index.get("unique") is True
    assert stripe_index.get("sparse") is True


async def test_rejects_second_connected_account_for_same_academy(db, migration, acad) -> None:
    await migration.up(db)

    await db["academy_connected_accounts"].insert_one(
        {"academy_id": acad, "stripe_account_id": "acct_A", "status": "pending"}
    )
    with pytest.raises(DuplicateKeyError):
        await db["academy_connected_accounts"].insert_one(
            {"academy_id": acad, "stripe_account_id": "acct_B", "status": "pending"}
        )


async def test_rejects_duplicate_stripe_account_id_across_academies(
    db, migration, acad, other_acad
) -> None:
    """Defense-in-depth: the webhook Connect-account guard trusts
    ``stripe_account_id`` to resolve tenant identity, so the same Stripe
    account id must never be attributable to two different academies at the
    database layer, even if application code had a bug."""
    await migration.up(db)

    await db["academy_connected_accounts"].insert_one(
        {"academy_id": acad, "stripe_account_id": "acct_shared", "status": "pending"}
    )
    with pytest.raises(DuplicateKeyError):
        await db["academy_connected_accounts"].insert_one(
            {"academy_id": other_acad, "stripe_account_id": "acct_shared", "status": "pending"}
        )


async def test_allows_one_account_per_academy(db, migration, acad, other_acad) -> None:
    await migration.up(db)

    await db["academy_connected_accounts"].insert_one(
        {"academy_id": acad, "stripe_account_id": "acct_A", "status": "pending"}
    )
    await db["academy_connected_accounts"].insert_one(
        {"academy_id": other_acad, "stripe_account_id": "acct_B", "status": "pending"}
    )
    assert await db["academy_connected_accounts"].count_documents({}) == 2
