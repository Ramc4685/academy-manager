"""Application tests for the legacy invoice ↔ Stripe charge review queue (#242 WI-3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

import pytest

from backend.v2.contexts.billing.application.use_cases.match_legacy_invoices import (
    ConfirmLegacyMatch,
    ConfirmLegacyMatchCommand,
    ListLegacyMatchQueue,
)
from backend.v2.contexts.billing.domain.ledger import (
    InvoiceLine,
    LedgerAllocationResult,
    LedgerInvoice,
    LedgerPayment,
    PaymentAllocation,
    allocate_payment_to_invoice,
)

_NOW = datetime(2026, 6, 23, 12, 0, tzinfo=UTC)
# A historical charge created near the invoice's due date.
_CHARGE_EPOCH = int(datetime(2026, 6, 28, 9, 0, tzinfo=UTC).timestamp())


def _invoice(
    *,
    invoice_id: str = "inv-1",
    parent_id: str = "parent-1",
    status: str = "open",
    total_cents: int = 7_000,
    balance_due_cents: int = 7_000,
) -> LedgerInvoice:
    return LedgerInvoice(
        invoice_id=invoice_id,
        academy_id="acad",
        parent_id=parent_id,
        student_id="student-1",
        enrollment_id="enr-1",
        period="2026-06",
        status=status,  # type: ignore[arg-type]
        subtotal_cents=total_cents,
        discount_cents=0,
        total_cents=total_cents,
        balance_due_cents=balance_due_cents,
        currency="usd",
        due_date=date(2026, 6, 30),
        created_at=_NOW,
        updated_at=_NOW,
    )


def _charge(
    *,
    charge_id: str = "ch_legacy_1",
    amount: int = 7_000,
    payment_intent: str | None = "pi_legacy_1",
    status: str = "succeeded",
    refunded: bool = False,
) -> dict[str, Any]:
    return {
        "id": charge_id,
        "object": "charge",
        "amount": amount,
        "currency": "usd",
        "status": status,
        "paid": True,
        "refunded": refunded,
        "payment_intent": payment_intent,
        "created": _CHARGE_EPOCH,
        "description": "Legacy tuition",
    }


@dataclass
class FakeParentCustomers:
    customers: dict[str, str] = field(default_factory=dict)

    async def get_stripe_customer_id(self, *, parent_id: str) -> str | None:
        return self.customers.get(parent_id)


@dataclass
class FakeStripe:
    charges_by_customer: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    list_calls: list[str] = field(default_factory=list)

    async def list_charges_for_customer(
        self, *, stripe_customer_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        self.list_calls.append(stripe_customer_id)
        return self.charges_by_customer.get(stripe_customer_id, [])[:limit]


@dataclass
class FakeLedger:
    invoices: dict[str, LedgerInvoice] = field(default_factory=dict)
    lines: dict[str, list[InvoiceLine]] = field(default_factory=dict)
    unmatched: list[dict[str, Any]] = field(default_factory=list)
    payments: dict[str, LedgerPayment] = field(default_factory=dict)
    allocations: dict[str, PaymentAllocation] = field(default_factory=dict)
    payment_idempotency: dict[str, str] = field(default_factory=dict)
    allocation_idempotency: dict[str, str] = field(default_factory=dict)

    async def list_unmatched_invoices(self) -> list[dict[str, Any]]:
        return self.unmatched

    async def get_invoice(self, invoice_id: str) -> LedgerInvoice | None:
        return self.invoices.get(invoice_id)

    async def get_payment_by_stripe_payment_intent_id(
        self, stripe_payment_intent_id: str
    ) -> LedgerPayment | None:
        return next(
            (
                p
                for p in self.payments.values()
                if p.stripe_payment_intent_id == stripe_payment_intent_id
            ),
            None,
        )

    async def get_payment_allocation_by_idempotency_key(
        self, idempotency_key: str
    ) -> PaymentAllocation | None:
        allocation_id = self.allocation_idempotency.get(idempotency_key)
        return self.allocations.get(allocation_id or "")

    async def record_payment(
        self, payment: LedgerPayment, *, idempotency_key: str
    ) -> LedgerPayment:
        existing_id = self.payment_idempotency.get(idempotency_key)
        if existing_id:
            return self.payments[existing_id]
        self.payments[payment.payment_id] = payment
        self.payment_idempotency[idempotency_key] = payment.payment_id
        return payment

    async def allocate_payment(
        self, *, payment_id: str, invoice_id: str, amount_cents: int, idempotency_key: str
    ) -> LedgerAllocationResult:
        existing = await self.get_payment_allocation_by_idempotency_key(idempotency_key)
        if existing is not None:
            return LedgerAllocationResult(
                invoice=self.invoices[existing.invoice_id],
                payment=self.payments[existing.payment_id],
                allocation=existing,
                overpayment_credit=None,
            )
        result = allocate_payment_to_invoice(
            invoice=self.invoices[invoice_id],
            payment=self.payments[payment_id],
            lines=self.lines.get(invoice_id, []),
            requested_amount_cents=amount_cents,
            allocation_id=f"alloc-{len(self.allocations) + 1}",
            now=_NOW,
        )
        self.invoices[invoice_id] = result.invoice
        self.payments[payment_id] = result.payment
        self.allocations[result.allocation.allocation_id] = result.allocation
        self.allocation_idempotency[idempotency_key] = result.allocation.allocation_id
        return result


def _row_from_invoice(inv: LedgerInvoice) -> dict[str, Any]:
    return {
        "invoice_id": inv.invoice_id,
        "parent_id": inv.parent_id,
        "period": inv.period,
        "status": inv.status,
        "total_cents": inv.total_cents,
        "balance_due_cents": inv.balance_due_cents,
        "currency": inv.currency,
        "due_date": inv.due_date,
        "created_at": inv.created_at,
        "stripe_invoice_id": None,
    }


# --------------------------------------------------------------------------- #
# ListLegacyMatchQueue
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_queue_surfaces_amount_matching_charge_without_allocating() -> None:
    invoice = _invoice()
    ledger = FakeLedger(invoices={"inv-1": invoice}, unmatched=[_row_from_invoice(invoice)])
    stripe = FakeStripe(charges_by_customer={"cus_1": [_charge()]})
    customers = FakeParentCustomers(customers={"parent-1": "cus_1"})

    rows = await ListLegacyMatchQueue(
        ledger=ledger, stripe=stripe, parent_customers=customers
    ).execute()

    assert len(rows) == 1
    row = rows[0]
    assert row.stripe_customer_id == "cus_1"
    assert [c.stripe_charge_id for c in row.candidates] == ["ch_legacy_1"]
    assert row.candidates[0].confidence == "high"  # exact balance + near due date
    # Nothing was auto-allocated.
    assert ledger.allocations == {}
    assert ledger.invoices["inv-1"].status == "open"


@pytest.mark.asyncio
async def test_queue_skips_non_matching_amounts_and_refunds() -> None:
    invoice = _invoice()
    ledger = FakeLedger(invoices={"inv-1": invoice}, unmatched=[_row_from_invoice(invoice)])
    stripe = FakeStripe(
        charges_by_customer={
            "cus_1": [
                _charge(charge_id="ch_wrong_amt", amount=1_234, payment_intent="pi_a"),
                _charge(charge_id="ch_refunded", refunded=True, payment_intent="pi_b"),
                _charge(charge_id="ch_failed", status="failed", payment_intent="pi_c"),
            ]
        }
    )
    customers = FakeParentCustomers(customers={"parent-1": "cus_1"})

    rows = await ListLegacyMatchQueue(
        ledger=ledger, stripe=stripe, parent_customers=customers
    ).execute()

    assert rows[0].candidates == []


@pytest.mark.asyncio
async def test_queue_excludes_charge_already_in_ledger() -> None:
    invoice = _invoice()
    ledger = FakeLedger(invoices={"inv-1": invoice}, unmatched=[_row_from_invoice(invoice)])
    # A ledger payment already references this charge's PaymentIntent.
    ledger.payments["existing"] = LedgerPayment(
        payment_id="existing",
        academy_id="acad",
        parent_id="parent-1",
        amount_cents=7_000,
        unapplied_amount_cents=0,
        currency="usd",
        status="succeeded",
        stripe_payment_intent_id="pi_legacy_1",
        created_at=_NOW,
        updated_at=_NOW,
    )
    stripe = FakeStripe(charges_by_customer={"cus_1": [_charge()]})
    customers = FakeParentCustomers(customers={"parent-1": "cus_1"})

    rows = await ListLegacyMatchQueue(
        ledger=ledger, stripe=stripe, parent_customers=customers
    ).execute()

    assert rows[0].candidates == []


@pytest.mark.asyncio
async def test_queue_no_customer_yields_empty_candidates_and_no_stripe_call() -> None:
    invoice = _invoice()
    ledger = FakeLedger(invoices={"inv-1": invoice}, unmatched=[_row_from_invoice(invoice)])
    stripe = FakeStripe()
    customers = FakeParentCustomers(customers={})  # parent has no Stripe customer

    rows = await ListLegacyMatchQueue(
        ledger=ledger, stripe=stripe, parent_customers=customers
    ).execute()

    assert rows[0].candidates == []
    assert rows[0].stripe_customer_id is None
    assert stripe.list_calls == []


# --------------------------------------------------------------------------- #
# ConfirmLegacyMatch
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_confirm_records_backdated_payment_and_marks_invoice_paid() -> None:
    ledger = FakeLedger(invoices={"inv-1": _invoice()})
    paid_at = datetime(2026, 6, 28, 9, 0, tzinfo=UTC)

    result = await ConfirmLegacyMatch(ledger=ledger, clock=lambda: _NOW).execute(
        ConfirmLegacyMatchCommand(
            invoice_id="inv-1",
            stripe_charge_id="ch_legacy_1",
            amount_cents=7_000,
            stripe_payment_intent_id="pi_legacy_1",
            paid_at=paid_at,
            recorded_by="admin-9",
        )
    )

    assert result.invoice_status == "paid"
    assert result.balance_due_cents == 0
    payment = ledger.payments[result.payment_id]
    assert payment.paid_at == paid_at  # back-dated, not "now"
    assert payment.recorded_by == "admin-9"
    assert payment.stripe_payment_intent_id == "pi_legacy_1"
    assert "ch_legacy_1" in (payment.notes or "")
    assert len(ledger.allocations) == 1


@pytest.mark.asyncio
async def test_confirm_is_idempotent_on_rerun() -> None:
    ledger = FakeLedger(invoices={"inv-1": _invoice()})
    cmd = ConfirmLegacyMatchCommand(
        invoice_id="inv-1",
        stripe_charge_id="ch_legacy_1",
        amount_cents=7_000,
        stripe_payment_intent_id="pi_legacy_1",
    )
    uc = ConfirmLegacyMatch(ledger=ledger, clock=lambda: _NOW)

    await uc.execute(cmd)
    await uc.execute(cmd)

    assert len(ledger.payments) == 1
    assert len(ledger.allocations) == 1
    assert ledger.invoices["inv-1"].status == "paid"


@pytest.mark.asyncio
async def test_confirm_rejects_overpayment() -> None:
    ledger = FakeLedger(invoices={"inv-1": _invoice(balance_due_cents=5_000)})

    with pytest.raises(ValueError, match="exceeds"):
        await ConfirmLegacyMatch(ledger=ledger, clock=lambda: _NOW).execute(
            ConfirmLegacyMatchCommand(
                invoice_id="inv-1",
                stripe_charge_id="ch_legacy_1",
                amount_cents=7_000,
            )
        )


@pytest.mark.asyncio
async def test_confirm_rejects_unpayable_invoice() -> None:
    ledger = FakeLedger(invoices={"inv-1": _invoice(status="paid", balance_due_cents=0)})

    with pytest.raises(ValueError, match="not payable"):
        await ConfirmLegacyMatch(ledger=ledger, clock=lambda: _NOW).execute(
            ConfirmLegacyMatchCommand(
                invoice_id="inv-1",
                stripe_charge_id="ch_legacy_1",
                amount_cents=7_000,
            )
        )
