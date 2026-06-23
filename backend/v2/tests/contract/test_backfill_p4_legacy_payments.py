from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.scripts import backfill_p4_legacy_payments as backfill


@pytest.mark.asyncio
async def test_backfill_inserts_missing_records_when_invoice_already_exists(db) -> None:
    now = datetime(2026, 6, 20, 10, 0, tzinfo=UTC)
    await db["payments"].insert_one(
        {
            "academy_id": "blno",
            "payment_id": "legacy-pay-1",
            "parent_id": "parent-1",
            "student_id": "student-1",
            "enrollment_id": "enroll-1",
            "amount_cents": 7000,
            "status": "succeeded",
            "created_at": now,
            "updated_at": now,
        }
    )
    await db["invoices"].insert_one(
        {
            "academy_id": "blno",
            "invoice_id": "inv-from-legacy-pay-1",
            "parent_id": "parent-1",
            "total_cents": 7000,
            "balance_due_cents": 0,
        }
    )

    result = await backfill.backfill_legacy_payments(db, academy_id="blno", dry_run=False)

    assert result["fatal_count"] == 0
    assert (
        await db["invoices"].count_documents(
            {"academy_id": "blno", "invoice_id": "inv-from-legacy-pay-1"}
        )
        == 1
    )
    assert (
        await db["invoice_lines"].count_documents(
            {"academy_id": "blno", "invoice_id": "inv-from-legacy-pay-1"}
        )
        == 1
    )
    assert (
        await db["ledger_payments"].count_documents(
            {"academy_id": "blno", "payment_id": "lp-from-legacy-pay-1"}
        )
        == 1
    )
    assert (
        await db["payment_allocations"].count_documents(
            {"academy_id": "blno", "allocation_id": "alloc-from-legacy-pay-1"}
        )
        == 1
    )


@pytest.mark.asyncio
async def test_backfill_idempotency_is_scoped_by_academy(db) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    await db["payments"].insert_one(
        {
            "academy_id": "acad-request",
            "payment_id": "pay-shared",
            "parent_id": "parent-1",
            "amount_cents": 6000,
            "status": "pending",
            "created_at": now,
            "updated_at": now,
        }
    )
    await db["invoices"].insert_one(
        {
            "academy_id": "other-acad",
            "invoice_id": "inv-from-pay-shared",
            "backfill_payment_id": "pay-shared",
        }
    )

    result = await backfill.backfill_legacy_payments(db, academy_id="acad-request", dry_run=False)

    assert result["fatal_count"] == 0
    assert result["already_backfilled"] == 0
    invoice = await db["invoices"].find_one(
        {"academy_id": "acad-request", "invoice_id": "inv-from-pay-shared"}
    )
    assert invoice is not None
    assert invoice["balance_due_cents"] == 6000
