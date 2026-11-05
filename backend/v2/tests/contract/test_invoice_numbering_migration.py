"""Migration smoke test: 0138_invoice_numbering.

Verifies the migration is idempotent (safe to re-run) and actually creates
the unique (academy_id, invoice_number) index used to catch any accidental
double-mint, plus does not corrupt existing invoice documents.
"""

from __future__ import annotations

import importlib
from datetime import UTC, datetime

import pytest
from pymongo.errors import DuplicateKeyError


def _invoice(academy_id: str, invoice_id: str) -> dict[str, object]:
    """Every field the 0138 invoices validator requires (real Mongo enforces it)."""
    now = datetime(2026, 6, 1, tzinfo=UTC)
    return {
        "academy_id": academy_id,
        "invoice_id": invoice_id,
        "invoice_number": "BLNO-202606-001",
        "parent_id": "par-1",
        "status": "open",
        "total_cents": 100,
        "balance_due_cents": 100,
        "currency": "usd",
        "created_at": now,
        "updated_at": now,
    }


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

    await db["invoices"].insert_one(_invoice(acad, "inv-1"))
    with pytest.raises(DuplicateKeyError):
        await db["invoices"].insert_one(_invoice(acad, "inv-2"))


async def test_migration_allows_same_invoice_number_across_different_academies(
    db, migration, acad, other_acad
) -> None:
    await migration.up(db)

    await db["invoices"].insert_one(_invoice(acad, "inv-1"))
    # Same invoice_number, different academy — must not collide.
    await db["invoices"].insert_one(_invoice(other_acad, "inv-2"))
    assert await db["invoices"].count_documents({}) == 2
