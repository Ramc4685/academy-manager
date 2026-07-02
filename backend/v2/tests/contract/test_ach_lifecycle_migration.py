import importlib
from datetime import UTC, date, datetime

import pytest

from backend.v2.contexts.billing.domain.ledger import LedgerInvoice, LedgerPayment
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)

pytestmark = pytest.mark.asyncio


async def test_0142_parent_payment_method_projection_is_backward_compatible(db, acad) -> None:
    migration = importlib.import_module("backend.v2.migrations.0142_ach_lifecycle")

    await migration.up(db)

    now = datetime.now(UTC)
    await db["parent_billing_customers"].insert_one(
        {
            "academy_id": acad,
            "parent_id": "parent-old",
            "stripe_customer_id": "cus_old",
            "default_payment_method_id": "pm_old",
            "payment_method_type": "card",
            "created_at": now,
            "updated_at": now,
        }
    )
    await db["parent_billing_customers"].insert_one(
        {
            "academy_id": acad,
            "parent_id": "parent-new",
            "stripe_customer_id": "cus_new",
            "default_payment_method_id": "pm_bank",
            "payment_method_type": "us_bank_account",
            "primary_payment_method_id": "pm_bank",
            "primary_payment_method_type": "us_bank_account",
            "primary_setup_status": "verification_required",
            "primary_stripe_mandate_id": "mandate_bank",
            "fallback_payment_method_id": "pm_card",
            "fallback_payment_method_type": "card",
            "fallback_setup_status": "active",
            "autopay_payment_methods": [
                {
                    "role": "primary",
                    "stripe_payment_method_id": "pm_bank",
                    "payment_method_type": "us_bank_account",
                    "stripe_mandate_id": "mandate_bank",
                    "setup_intent_id": "seti_bank",
                    "setup_status": "verification_required",
                    "updated_at": now,
                },
                {
                    "role": "fallback",
                    "stripe_payment_method_id": "pm_card",
                    "payment_method_type": "card",
                    "setup_intent_id": "seti_card",
                    "setup_status": "active",
                    "updated_at": now,
                },
            ],
            "created_at": now,
            "updated_at": now,
        }
    )

    assert await db["parent_billing_customers"].count_documents({"academy_id": acad}) == 2


async def test_0142_creates_payment_allocation_reversal_indexes(db, acad) -> None:
    migration = importlib.import_module("backend.v2.migrations.0142_ach_lifecycle")

    await migration.up(db)

    names = {index["name"] async for index in db["payment_allocation_reversals"].list_indexes()}
    assert "uniq_payment_allocation_reversal_idempotency" in names
    assert "payment_allocation_reversal_payment_lookup" in names


async def test_reverse_payment_allocation_replay_repairs_after_preinserted_reversal(
    db, acad
) -> None:
    repo = MongoBillingLedgerRepository(db)
    now = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    invoice = LedgerInvoice(
        invoice_id="inv-reversal-replay",
        academy_id=acad,
        parent_id="parent-1",
        period="2026-07",
        status="open",
        subtotal_cents=10_000,
        discount_cents=0,
        total_cents=10_000,
        balance_due_cents=10_000,
        currency="usd",
        due_date=date(2026, 7, 31),
        created_at=now,
        updated_at=now,
    )
    payment = LedgerPayment(
        payment_id="pay-reversal-replay",
        academy_id=acad,
        parent_id="parent-1",
        amount_cents=10_000,
        unapplied_amount_cents=10_000,
        currency="usd",
        status="succeeded",
        payment_method="stripe_autopay",
        stripe_payment_intent_id="pi_reversal_replay",
        paid_at=now,
        metadata={"funding_type": "us_bank_account"},
        created_at=now,
        updated_at=now,
    )
    await repo.create_invoice(invoice, lines=[], idempotency_key="invoice:reversal-replay")
    await repo.record_payment(payment, idempotency_key="payment:reversal-replay")
    await repo.allocate_payment(
        payment_id=payment.payment_id,
        invoice_id=invoice.invoice_id,
        amount_cents=10_000,
        idempotency_key="autopay-alloc:pi_reversal_replay",
    )
    await repo.mark_payment_refunded(
        payment.payment_id,
        refunded_cents=10_000,
        status="refunded",
        updated_at=now,
    )
    allocation = await db["payment_allocations"].find_one(
        {"academy_id": acad, "idempotency_key": "autopay-alloc:pi_reversal_replay"}
    )
    assert allocation is not None
    await db["payment_allocation_reversals"].insert_one(
        {
            "reversal_id": "rev-preinserted",
            "academy_id": acad,
            "allocation_id": allocation["allocation_id"],
            "payment_id": payment.payment_id,
            "invoice_id": invoice.invoice_id,
            "amount_cents": 10_000,
            "reason": "ach_return",
            "return_code": "R01",
            "idempotency_key": "ach-return:pi_reversal_replay:10000:R01",
            "created_at": now,
        }
    )

    await repo.reverse_payment_allocation(
        allocation_idempotency_key="autopay-alloc:pi_reversal_replay",
        reversal_idempotency_key="ach-return:pi_reversal_replay:10000:R01",
        reason="ach_return",
        return_code="R01",
        reversed_at=now,
    )

    assert (
        await db["payment_allocations"].find_one(
            {"academy_id": acad, "idempotency_key": "autopay-alloc:pi_reversal_replay"}
        )
        is None
    )
    repaired_invoice = await repo.get_invoice(invoice.invoice_id)
    repaired_payment = await repo.get_payment_by_stripe_payment_intent_id("pi_reversal_replay")
    assert repaired_invoice is not None
    assert repaired_invoice.status == "open"
    assert repaired_invoice.balance_due_cents == 10_000
    assert repaired_payment is not None
    assert repaired_payment.status == "refunded"
    assert repaired_payment.unapplied_amount_cents == 0


async def test_mongo_billing_ledger_repo_exposes_ach_lifecycle_port_methods() -> None:
    for method_name in (
        "get_payment_by_stripe_payment_intent_id",
        "get_payment_allocation_by_idempotency_key",
        "mark_payment_refunded",
        "record_payment_attempt",
        "reverse_payment_allocation",
    ):
        assert callable(getattr(MongoBillingLedgerRepository, method_name, None))
