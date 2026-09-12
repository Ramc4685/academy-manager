"""Issue #679: ``ledger_payments.stripe_payment_intent_id`` needs a DB guard.

Every settlement path dedupes on the payment intent, but nothing enforced
uniqueness, so a replayed webhook could record the same money twice. These
tests pin the partial unique index the migration adds, the manual-payment
carve-out the partial filter buys, and the "log and skip rather than crash
boot" behaviour when production already holds duplicates.
"""

from __future__ import annotations

import importlib
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from pymongo.errors import DuplicateKeyError

from backend.scripts.ledger_payment_intent_duplicate_audit import audit
from backend.v2.migrations import runner

MODULE_NAME = "backend.v2.migrations.0173_ledger_payment_intent_unique_index"
INDEX_NAME = "academy_ledger_payment_intent_unique"

NOW = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)


@pytest.fixture
def migration():
    return importlib.import_module(MODULE_NAME)


def _payment(payment_id: str, *, academy_id: str = "acad-1", intent: str | None = None) -> dict:
    doc = {
        "academy_id": academy_id,
        "payment_id": payment_id,
        "parent_id": "parent-1",
        "amount_cents": 5_000,
        "unapplied_amount_cents": 0,
        "currency": "usd",
        "status": "succeeded",
        "created_at": NOW,
        "updated_at": NOW,
    }
    if intent is not None:
        doc["stripe_payment_intent_id"] = intent
    return doc


@pytest.mark.asyncio
async def test_migration_is_discovered_by_the_runner(migration) -> None:
    assert MODULE_NAME in {module.__name__ for module in runner._discover_migrations()}
    assert migration.version == MODULE_NAME.rsplit(".", 1)[-1]


@pytest.mark.asyncio
async def test_creates_the_partial_unique_index(db, migration) -> None:
    await migration.up(db)

    index = (await db["ledger_payments"].index_information())[INDEX_NAME]
    assert index["key"] == [("academy_id", 1), ("stripe_payment_intent_id", 1)]
    assert index["unique"] is True
    assert index["partialFilterExpression"] == {"stripe_payment_intent_id": {"$type": "string"}}


@pytest.mark.asyncio
async def test_rejects_a_replayed_payment_intent_in_the_same_academy(db, migration) -> None:
    await migration.up(db)
    await db["ledger_payments"].insert_one(_payment("pay-1", intent="pi_123"))

    with pytest.raises(DuplicateKeyError):
        await db["ledger_payments"].insert_one(_payment("pay-2", intent="pi_123"))


@pytest.mark.asyncio
async def test_scopes_the_constraint_to_one_academy(db, migration) -> None:
    await migration.up(db)
    await db["ledger_payments"].insert_one(_payment("pay-1", intent="pi_123"))

    await db["ledger_payments"].insert_one(_payment("pay-2", academy_id="acad-2", intent="pi_123"))

    assert await db["ledger_payments"].count_documents({}) == 2


@pytest.mark.asyncio
async def test_leaves_manual_payments_without_an_intent_unconstrained(db, migration) -> None:
    await migration.up(db)

    await db["ledger_payments"].insert_one(_payment("cash-1"))
    await db["ledger_payments"].insert_one(_payment("zelle-1"))

    assert await db["ledger_payments"].count_documents({}) == 2


@pytest.mark.asyncio
async def test_tolerates_preexisting_duplicates_instead_of_crashing_boot(db, migration) -> None:
    await db["ledger_payments"].insert_one(_payment("pay-1", intent="pi_dup"))
    await db["ledger_payments"].insert_one(_payment("pay-2", intent="pi_dup"))

    await migration.up(db)

    assert INDEX_NAME not in await db["ledger_payments"].index_information()


@pytest.mark.asyncio
async def test_builds_the_index_in_the_background(migration) -> None:
    payments = MagicMock()
    payments.create_index = AsyncMock()
    db = MagicMock()
    db.__getitem__ = MagicMock(return_value=payments)

    await migration.up(db)

    kwargs = payments.create_index.await_args.kwargs
    assert kwargs["background"] is True
    assert kwargs["unique"] is True
    assert kwargs["name"] == INDEX_NAME


@pytest.mark.asyncio
async def test_duplicate_audit_reports_the_offending_groups(db) -> None:
    await db["ledger_payments"].insert_one(_payment("pay-1", intent="pi_dup"))
    await db["ledger_payments"].insert_one(_payment("pay-2", intent="pi_dup"))
    await db["ledger_payments"].insert_one(_payment("pay-3", intent="pi_unique"))
    await db["ledger_payments"].insert_one(_payment("cash-1"))
    await db["ledger_payments"].insert_one(_payment("cash-2"))
    await db["payment_allocations"].insert_one(
        {
            "allocation_id": "alloc-1",
            "academy_id": "acad-1",
            "payment_id": "pay-2",
            "invoice_id": "inv-1",
            "amount_cents": 5_000,
            "created_at": NOW,
        }
    )
    await db["account_credit_ledger"].insert_one(
        {
            "credit_id": "credit-1",
            "academy_id": "acad-1",
            "parent_id": "parent-1",
            "source_type": "OVERPAYMENT",
            "source_id": "pay-2",
            "amount_cents": 5_000,
            "remaining_amount_cents": 5_000,
            "status": "APPROVED",
        }
    )

    report = await audit(db)

    assert report["duplicate_group_count"] == 1
    assert report["scanned_payments_with_intent"] == 3
    (group,) = report["duplicate_groups"]
    assert group["academy_id"] == "acad-1"
    assert group["stripe_payment_intent_id"] == "pi_dup"
    assert [payment["payment_id"] for payment in group["payments"]] == ["pay-1", "pay-2"]
    duplicate = group["payments"][1]
    assert [alloc["allocation_id"] for alloc in duplicate["allocations"]] == ["alloc-1"]
    assert [credit["credit_id"] for credit in duplicate["credits"]] == ["credit-1"]


@pytest.mark.asyncio
async def test_duplicate_audit_is_clean_when_every_intent_is_unique(db) -> None:
    await db["ledger_payments"].insert_one(_payment("pay-1", intent="pi_1"))
    await db["ledger_payments"].insert_one(_payment("pay-2", intent="pi_2"))
    await db["ledger_payments"].insert_one(_payment("pay-3", academy_id="acad-2", intent="pi_1"))

    report = await audit(db)

    assert report["duplicate_group_count"] == 0
    assert report["duplicate_groups"] == []
