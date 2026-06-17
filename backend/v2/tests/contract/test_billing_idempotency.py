from __future__ import annotations

import importlib
from datetime import UTC, date, datetime

import pytest

from backend.v2.contexts.billing.domain.ledger import (
    InvoiceLine,
    LedgerInvoice,
    LedgerPayment,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.shared.tenancy import tenant_scope


@pytest.mark.asyncio
async def test_invoice_creation_is_idempotent_per_tenant(db, acad) -> None:
    repo = MongoBillingLedgerRepository(db)
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    invoice = LedgerInvoice(
        invoice_id="inv-idempotent",
        academy_id=acad,
        parent_id="parent-1",
        student_id="student-1",
        enrollment_id="enroll-1",
        period="2026-06",
        status="open",
        subtotal_cents=10_000,
        discount_cents=0,
        total_cents=10_000,
        balance_due_cents=10_000,
        currency="usd",
        due_date=date(2026, 6, 10),
        created_at=now,
        updated_at=now,
    )
    lines = [
        InvoiceLine(
            line_id="line-idempotent",
            academy_id=acad,
            invoice_id="inv-idempotent",
            line_type="tuition",
            description="June tuition",
            quantity=1,
            unit_amount_cents=10_000,
            amount_cents=10_000,
            source_type="enrollment",
            source_id="enroll-1",
            created_at=now,
        )
    ]

    first = await repo.create_invoice(
        invoice,
        lines=lines,
        idempotency_key="invoice:enroll-1:2026-06",
    )
    second = await repo.create_invoice(
        invoice,
        lines=lines,
        idempotency_key="invoice:enroll-1:2026-06",
    )

    assert first == second
    assert await db["invoices"].count_documents({"academy_id": acad}) == 1
    assert await db["invoice_lines"].count_documents({"academy_id": acad}) == 1


@pytest.mark.asyncio
async def test_allocation_overpayment_credit_is_idempotent(db, acad) -> None:
    repo = MongoBillingLedgerRepository(db)
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    await repo.create_invoice(
        LedgerInvoice(
            invoice_id="inv-overpay",
            academy_id=acad,
            parent_id="parent-1",
            period="2026-06",
            status="open",
            subtotal_cents=10_000,
            discount_cents=0,
            total_cents=10_000,
            balance_due_cents=10_000,
            currency="usd",
            due_date=date(2026, 6, 10),
            created_at=now,
            updated_at=now,
        ),
        lines=[],
        idempotency_key="invoice:overpay",
    )
    await repo.record_payment(
        LedgerPayment(
            payment_id="pay-overpay",
            academy_id=acad,
            parent_id="parent-1",
            amount_cents=12_000,
            unapplied_amount_cents=12_000,
            currency="usd",
            status="succeeded",
            payment_method="cash",
            paid_at=now,
            created_at=now,
            updated_at=now,
        ),
        idempotency_key="payment:manual:receipt-1",
    )

    first = await repo.allocate_payment(
        payment_id="pay-overpay",
        invoice_id="inv-overpay",
        amount_cents=12_000,
        idempotency_key="allocation:receipt-1:inv-overpay",
    )
    second = await repo.allocate_payment(
        payment_id="pay-overpay",
        invoice_id="inv-overpay",
        amount_cents=12_000,
        idempotency_key="allocation:receipt-1:inv-overpay",
    )

    assert first == second
    invoice = await db["invoices"].find_one({"academy_id": acad, "invoice_id": "inv-overpay"})
    payment = await db["ledger_payments"].find_one(
        {"academy_id": acad, "payment_id": "pay-overpay"}
    )
    assert invoice is not None
    assert payment is not None
    assert (
        await db["payments"].count_documents({"academy_id": acad, "payment_id": "pay-overpay"}) == 0
    )
    assert invoice["balance_due_cents"] == 0
    assert invoice["status"] == "paid"
    assert payment["unapplied_amount_cents"] == 0
    assert await db["payment_allocations"].count_documents({"academy_id": acad}) == 1
    credits = [doc async for doc in db["account_credit_ledger"].find({"academy_id": acad})]
    assert len(credits) == 1
    assert credits[0]["type"] == "MANUAL_CREDIT"
    assert credits[0]["source_type"] == "OVERPAYMENT"
    assert credits[0]["source_id"] == first.allocation.allocation_id
    assert credits[0]["amount_cents"] == 2_000
    assert credits[0]["remaining_amount_cents"] == 2_000


@pytest.mark.asyncio
async def test_billing_ledger_reads_are_tenant_isolated(db, acad) -> None:
    repo = MongoBillingLedgerRepository(db)
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    await repo.create_invoice(
        LedgerInvoice(
            invoice_id="inv-tenant",
            academy_id=acad,
            parent_id="parent-1",
            period="2026-06",
            status="open",
            subtotal_cents=5_000,
            discount_cents=0,
            total_cents=5_000,
            balance_due_cents=5_000,
            currency="usd",
            due_date=date(2026, 6, 10),
            created_at=now,
            updated_at=now,
        ),
        lines=[],
        idempotency_key="invoice:tenant",
    )

    assert await repo.get_invoice("inv-tenant") is not None
    with tenant_scope("other-academy"):
        other_repo = MongoBillingLedgerRepository(db)
        assert await other_repo.get_invoice("inv-tenant") is None


@pytest.mark.asyncio
async def test_ledger_payment_storage_ignores_legacy_payments_collection(db, acad) -> None:
    repo = MongoBillingLedgerRepository(db)
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    await repo.create_invoice(
        LedgerInvoice(
            invoice_id="inv-storage-split",
            academy_id=acad,
            parent_id="parent-1",
            period="2026-06",
            status="open",
            subtotal_cents=5_000,
            discount_cents=0,
            total_cents=5_000,
            balance_due_cents=5_000,
            currency="usd",
            due_date=date(2026, 6, 10),
            created_at=now,
            updated_at=now,
        ),
        lines=[],
        idempotency_key="invoice:storage-split",
    )
    await db["payments"].insert_one(
        {
            "academy_id": acad,
            "payment_id": "pay-storage-split",
            "parent_id": "parent-1",
            "amount_cents": 5_000,
            "status": "succeeded",
            "ledger_idempotency_key": "payment:storage-split",
            "created_at": now,
            "updated_at": now,
        }
    )

    with pytest.raises(ValueError, match="payment not found"):
        await repo.allocate_payment(
            payment_id="pay-storage-split",
            invoice_id="inv-storage-split",
            amount_cents=5_000,
            idempotency_key="allocation:storage-split",
        )

    await repo.record_payment(
        LedgerPayment(
            payment_id="pay-storage-split",
            academy_id=acad,
            parent_id="parent-1",
            amount_cents=5_000,
            unapplied_amount_cents=5_000,
            currency="usd",
            status="succeeded",
            payment_method="cash",
            paid_at=now,
            created_at=now,
            updated_at=now,
        ),
        idempotency_key="payment:storage-split",
    )

    result = await repo.allocate_payment(
        payment_id="pay-storage-split",
        invoice_id="inv-storage-split",
        amount_cents=5_000,
        idempotency_key="allocation:storage-split",
    )

    assert result.invoice.status == "paid"
    assert (
        await db["ledger_payments"].count_documents(
            {"academy_id": acad, "payment_id": "pay-storage-split"}
        )
        == 1
    )


@pytest.mark.asyncio
async def test_ledger_payments_migration_copies_only_ledger_shape_without_deleting(
    db, acad
) -> None:
    migration = importlib.import_module("backend.v2.migrations.0128_ledger_payments_storage")
    audit_script = importlib.import_module("backend.scripts.ledger_payments_storage_audit")
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    await db["payments"].insert_many(
        [
            {
                "academy_id": acad,
                "payment_id": "pay-ledger-copy",
                "parent_id": "parent-1",
                "amount_cents": 5_000,
                "unapplied_amount_cents": 5_000,
                "ledger_idempotency_key": "payment:ledger-copy",
                "status": "succeeded",
                "created_at": now,
                "updated_at": now,
            },
            {
                "academy_id": acad,
                "payment_id": "pay-legacy-keep",
                "parent_id": "parent-1",
                "enrollment_id": "enroll-1",
                "amount_cents": 6_000,
                "status": "pending",
                "created_at": now,
                "updated_at": now,
            },
        ]
    )

    before = await audit_script.audit(db)
    assert before == {
        "legacy_ledger_shaped_payments": 1,
        "ledger_payments": 0,
        "missing_from_ledger_payments": 1,
    }

    await migration.up(db)
    await migration.up(db)

    after = await audit_script.audit(db)
    assert after == {
        "legacy_ledger_shaped_payments": 1,
        "ledger_payments": 1,
        "missing_from_ledger_payments": 0,
    }

    copied = await db["ledger_payments"].find_one(
        {"academy_id": acad, "payment_id": "pay-ledger-copy"}
    )
    assert copied is not None
    assert copied["ledger_idempotency_key"] == "payment:ledger-copy"
    assert await db["ledger_payments"].count_documents({"academy_id": acad}) == 1
    assert await db["payments"].count_documents({"academy_id": acad}) == 2
    assert await db["payments"].find_one({"academy_id": acad, "payment_id": "pay-legacy-keep"})
