from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.billing.domain.models import CreditLedgerEntry
from backend.v2.contexts.billing.infrastructure.mongo_credit_ledger_repo import (
    MongoCreditLedgerRepository,
)


@pytest.mark.asyncio
async def test_credit_ledger_fifo_application_is_atomic(db, acad) -> None:
    repo = MongoCreditLedgerRepository(db)
    now = datetime(2026, 5, 20, tzinfo=UTC)
    await repo.create(
        CreditLedgerEntry(
            credit_id="credit-1",
            academy_id=acad,
            parent_id="parent-1",
            student_id="student-1",
            enrollment_id="enroll-1",
            type="EARLY_WITHDRAWAL_CREDIT",
            status="APPROVED",
            amount_cents=3750,
            remaining_amount_cents=3750,
            currency="usd",
            reason="withdrawal",
            calculation_snapshot_id="snap-1",
            expires_at=datetime(2027, 5, 31, tzinfo=UTC),
            created_at=now,
            updated_at=now,
        )
    )

    applied = await repo.apply_available_credits(
        parent_id="parent-1", invoice_id="pay-1", amount_due_cents=1000
    )

    assert applied == 1000
    assert await repo.balance_for_parent("parent-1") == 2750
    applications = [doc async for doc in db["credit_applications"].find({})]
    assert len(applications) == 1
    assert applications[0]["amount_cents"] == 1000
    # New invariant: the credit doc itself records the applied invoice atomically.
    credit_doc = await db["account_credit_ledger"].find_one({"credit_id": "credit-1"})
    assert credit_doc is not None
    assert "pay-1" in credit_doc.get("applied_invoice_ids", [])


@pytest.mark.asyncio
async def test_credit_ledger_application_is_idempotent_per_invoice(db, acad) -> None:
    repo = MongoCreditLedgerRepository(db)
    now = datetime(2026, 5, 20, tzinfo=UTC)
    await repo.create(
        CreditLedgerEntry(
            credit_id="credit-1",
            academy_id=acad,
            parent_id="parent-1",
            type="MANUAL_CREDIT",
            status="APPROVED",
            amount_cents=2000,
            remaining_amount_cents=2000,
            currency="usd",
            reason="manual",
            expires_at=datetime(2027, 5, 31, tzinfo=UTC),
            created_at=now,
            updated_at=now,
        )
    )

    assert (
        await repo.apply_available_credits(
            parent_id="parent-1", invoice_id="pay-1", amount_due_cents=1000
        )
        == 1000
    )
    # Issue #233: a rerun reports the amount this invoice already consumed
    # instead of 0, so a caller recovering after a crash prices it net.
    assert (
        await repo.apply_available_credits(
            parent_id="parent-1", invoice_id="pay-1", amount_due_cents=1000
        )
        == 1000
    )
    # ...and the credit itself is not spent twice.
    assert await repo.balance_for_parent("parent-1") == 1000
    credit_doc = await db["account_credit_ledger"].find_one(
        {"academy_id": acad, "credit_id": "credit-1"}
    )
    assert credit_doc is not None
    assert credit_doc["applied_invoice_ids"] == ["pay-1"]
    assert [
        (entry["invoice_id"], entry["amount_cents"]) for entry in credit_doc["applications"]
    ] == [("pay-1", 1000)]
    assert (
        await db["credit_applications"].count_documents({"academy_id": acad, "invoice_id": "pay-1"})
        == 1
    )


@pytest.mark.asyncio
async def test_unapply_credits_restores_balance_after_invoice_void(db, acad) -> None:
    """Issue #784: voiding an invoice must give the family's credit back.

    The FIFO application spreads one invoice across several credit documents,
    so the reversal has to walk every matching document — and restore exactly
    what this invoice consumed, never a cent more.
    """
    repo = MongoCreditLedgerRepository(db)
    now = datetime(2026, 5, 20, tzinfo=UTC)
    for credit_id, amount in (("credit-1", 1200), ("credit-2", 3000)):
        await repo.create(
            CreditLedgerEntry(
                credit_id=credit_id,
                academy_id=acad,
                parent_id="parent-1",
                type="MANUAL_CREDIT",
                status="APPROVED",
                amount_cents=amount,
                remaining_amount_cents=amount,
                currency="usd",
                reason="manual",
                expires_at=datetime(2027, 5, 31, tzinfo=UTC),
                created_at=now,
                updated_at=now,
            )
        )

    assert (
        await repo.apply_available_credits(
            parent_id="parent-1", invoice_id="inv-1", amount_due_cents=2000
        )
        == 2000
    )
    # Spread across BOTH credits: 1200 from the first, 800 from the second.
    assert await repo.balance_for_parent("parent-1") == 2200

    restored = await repo.unapply_credits(
        invoice_id="inv-1", reason="admin_void", now=datetime(2026, 6, 1, tzinfo=UTC)
    )

    assert restored == 2000
    assert await repo.balance_for_parent("parent-1") == 4200
    for credit_id in ("credit-1", "credit-2"):
        doc = await db["account_credit_ledger"].find_one({"credit_id": credit_id})
        assert "inv-1" not in doc.get("applied_invoice_ids", [])
        assert all(app.get("invoice_id") != "inv-1" for app in doc.get("applications", []) or [])
    # The invoice no longer reads as having consumed credit.
    assert (await repo.applied_credit_state("inv-1")).applied_cents == 0


@pytest.mark.asyncio
async def test_unapply_credits_is_idempotent(db, acad) -> None:
    """A retry after a crash must not mint a second copy of the credit."""
    repo = MongoCreditLedgerRepository(db)
    now = datetime(2026, 5, 20, tzinfo=UTC)
    await repo.create(
        CreditLedgerEntry(
            credit_id="credit-1",
            academy_id=acad,
            parent_id="parent-1",
            type="MANUAL_CREDIT",
            status="APPROVED",
            amount_cents=2000,
            remaining_amount_cents=2000,
            currency="usd",
            reason="manual",
            created_at=now,
            updated_at=now,
        )
    )
    await repo.apply_available_credits(
        parent_id="parent-1", invoice_id="inv-1", amount_due_cents=500
    )

    assert await repo.unapply_credits(invoice_id="inv-1", reason="admin_void", now=now) == 500
    assert await repo.unapply_credits(invoice_id="inv-1", reason="admin_void", now=now) == 0
    assert await repo.balance_for_parent("parent-1") == 2000


@pytest.mark.asyncio
async def test_unapply_credits_ignores_other_invoices(db, acad) -> None:
    """Restoring one invoice's credit must not touch another invoice's."""
    repo = MongoCreditLedgerRepository(db)
    now = datetime(2026, 5, 20, tzinfo=UTC)
    await repo.create(
        CreditLedgerEntry(
            credit_id="credit-1",
            academy_id=acad,
            parent_id="parent-1",
            type="MANUAL_CREDIT",
            status="APPROVED",
            amount_cents=5000,
            remaining_amount_cents=5000,
            currency="usd",
            reason="manual",
            created_at=now,
            updated_at=now,
        )
    )
    await repo.apply_available_credits(
        parent_id="parent-1", invoice_id="inv-1", amount_due_cents=1000
    )
    await repo.apply_available_credits(
        parent_id="parent-1", invoice_id="inv-2", amount_due_cents=1500
    )
    assert await repo.balance_for_parent("parent-1") == 2500

    assert await repo.unapply_credits(invoice_id="inv-1", reason="admin_void", now=now) == 1000

    assert await repo.balance_for_parent("parent-1") == 3500
    assert (await repo.applied_credit_state("inv-2")).applied_cents == 1500
