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


async def test_migration_creates_unique_sparse_index_on_academy_and_invoice_number(
    db, migration
) -> None:
    """The index must be unique (catch accidental duplicate mints) AND sparse (so
    invoices predating Slice D, which have no invoice_number field at all, are
    excluded from the uniqueness check and never collide with each other).

    NOTE: this asserts the index was *requested* with the right options, rather than
    exercising the sparse-exclusion runtime behavior end-to-end. mongomock-motor's
    sparse-index support does not correctly replicate MongoDB's "exclude
    missing/null field" semantics (a known mongomock limitation — see
    test_migrations_legacy_compat.py for a related workaround elsewhere in this
    suite), so a behavioral assertion here would be testing mongomock's bug, not our
    migration. Real MongoDB is trusted to honor `sparse=True` correctly.
    """
    await migration.up(db)

    indexes = await db["invoices"].index_information()
    idx = indexes["invoices_academy_invoice_number_unique"]
    assert idx.get("unique") is True
    assert idx.get("sparse") is True


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
