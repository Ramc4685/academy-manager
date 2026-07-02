"""Migration smoke test: 0138_invoice_numbering.

Verifies the migration is idempotent (safe to re-run) and actually creates
the unique (academy_id, invoice_number) index used to catch any accidental
double-mint, plus does not corrupt existing invoice documents.
"""

from __future__ import annotations

import importlib

import pytest
from pymongo.errors import DuplicateKeyError


@pytest.fixture
def migration():
    return importlib.import_module("backend.v2.migrations.0138_invoice_numbering")


async def test_migration_is_idempotent(db, migration) -> None:
    await migration.up(db)
    await migration.up(db)  # second run must not raise

    indexes = await db["invoices"].index_information()
    assert "invoices_academy_invoice_number_unique" in indexes


async def test_migration_creates_unique_partial_index_on_academy_and_invoice_number(
    db, migration
) -> None:
    """The index must be unique and partial so legacy/null invoice numbers are excluded.

    A compound sparse index would still include rows with ``academy_id`` but no
    ``invoice_number``; the partial filter limits uniqueness to minted strings.
    """
    await migration.up(db)

    indexes = await db["invoices"].index_information()
    idx = indexes["invoices_academy_invoice_number_unique"]
    assert idx.get("unique") is True
    assert idx.get("partialFilterExpression") == {"invoice_number": {"$type": "string"}}


async def test_migration_rejects_duplicate_invoice_number_within_academy(
    db, migration, acad
) -> None:
    await migration.up(db)

    await db["invoices"].insert_one(
        {
            "academy_id": acad,
            "invoice_id": "inv-1",
            "invoice_number": "BLNO-202606-001",
            "status": "open",
        }
    )
    with pytest.raises(DuplicateKeyError):
        await db["invoices"].insert_one(
            {
                "academy_id": acad,
                "invoice_id": "inv-2",
                "invoice_number": "BLNO-202606-001",
                "status": "open",
            }
        )


async def test_migration_allows_same_invoice_number_across_different_academies(
    db, migration, acad, other_acad
) -> None:
    await migration.up(db)

    await db["invoices"].insert_one(
        {
            "academy_id": acad,
            "invoice_id": "inv-1",
            "invoice_number": "BLNO-202606-001",
            "status": "open",
        }
    )
    # Same invoice_number, different academy — must not collide.
    await db["invoices"].insert_one(
        {
            "academy_id": other_acad,
            "invoice_id": "inv-2",
            "invoice_number": "BLNO-202606-001",
            "status": "open",
        }
    )
    assert await db["invoices"].count_documents({}) == 2
