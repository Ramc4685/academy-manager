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

    assert await repo.apply_available_credits(
        parent_id="parent-1", invoice_id="pay-1", amount_due_cents=1000
    ) == 1000
    assert await repo.apply_available_credits(
        parent_id="parent-1", invoice_id="pay-1", amount_due_cents=1000
    ) == 0
    assert await repo.balance_for_parent("parent-1") == 1000
