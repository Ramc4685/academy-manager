"""Application tests for linking a legacy Stripe charge to an invoice (#242 WI-3).

The list half was deleted by the Billing Health trim (spec 2026-09-07 §2); only
the explicit, admin-named confirm remains.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

import pytest

from backend.v2.contexts.billing.application.use_cases.match_legacy_invoices import (
    ConfirmLegacyMatch,
    ConfirmLegacyMatchCommand,
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


@dataclass
class FakeParentCustomers:
    """Mirrors the real repo: a parent may simply have no Stripe customer."""

    customer_id: str | None = "cus_1"

    async def get_stripe_customer_id(self, *, parent_id: str) -> str | None:
        return self.customer_id


@dataclass
class FakeStripe:
    """Returns charge dicts shaped like Stripe's, keyed by customer.

    Deliberately NOT permissive: a charge id that was never issued to this
    customer is absent, exactly as the real list would leave it out. A fake that
    invented one would hide the parent-binding guard.
    """

    charges: list[dict[str, Any]] = field(default_factory=list)

    async def list_charges_for_customer(self, *, stripe_customer_id: str) -> list[dict[str, Any]]:
        return list(self.charges)


def _charge(
    *,
    charge_id: str = "ch_legacy_1",
    amount: int = 7_000,
    payment_intent: str | None = "pi_legacy_1",
    status: str = "succeeded",
    refunded: bool = False,
    paid: bool = True,
    currency: str = "usd",
) -> dict[str, Any]:
    return {
        "id": charge_id,
        "amount": amount,
        "currency": currency,
        "status": status,
        "paid": paid,
        "refunded": refunded,
        "payment_intent": payment_intent,
        "created": _CHARGE_EPOCH,
    }


def _uc(
    ledger: FakeLedger,
    *,
    charges: list[dict[str, Any]] | None = None,
    customer_id: str | None = "cus_1",
) -> ConfirmLegacyMatch:
    return ConfirmLegacyMatch(
        ledger=ledger,
        stripe=FakeStripe(charges=charges if charges is not None else [_charge()]),
        parent_customers=FakeParentCustomers(customer_id=customer_id),
        clock=lambda: _NOW,
    )


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
# ConfirmLegacyMatch
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_confirm_records_backdated_payment_and_marks_invoice_paid() -> None:
    ledger = FakeLedger(invoices={"inv-1": _invoice()})
    paid_at = datetime(2026, 6, 28, 9, 0, tzinfo=UTC)

    result = await _uc(ledger).execute(
        ConfirmLegacyMatchCommand(
            invoice_id="inv-1",
            stripe_charge_id="ch_legacy_1",
            amount_cents=7_000,
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
    )
    uc = _uc(ledger)

    await uc.execute(cmd)
    await uc.execute(cmd)

    assert len(ledger.payments) == 1
    assert len(ledger.allocations) == 1
    assert ledger.invoices["inv-1"].status == "paid"


@pytest.mark.asyncio
async def test_confirm_rejects_overpayment() -> None:
    ledger = FakeLedger(invoices={"inv-1": _invoice(balance_due_cents=5_000)})

    with pytest.raises(ValueError, match="exceeds"):
        await _uc(ledger, charges=[_charge(amount=7_000)]).execute(
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
        await _uc(ledger).execute(
            ConfirmLegacyMatchCommand(
                invoice_id="inv-1",
                stripe_charge_id="ch_legacy_1",
                amount_cents=7_000,
            )
        )


# --------------------------------------------------------------------------- #
# Verification against Stripe (the guarantees the deleted list used to give)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_confirm_records_stripes_payment_intent_not_the_charge_id() -> None:
    """The webhook and reconciler dedupe on the payment intent.

    Storing the charge id here instead left the same money bookable twice: once
    by hand, then again when the quarantined event was replayed, with the second
    copy landing as spendable parent credit.
    """
    ledger = FakeLedger(invoices={"inv-1": _invoice()})

    result = await _uc(ledger).execute(
        ConfirmLegacyMatchCommand(
            invoice_id="inv-1", stripe_charge_id="ch_legacy_1", amount_cents=7_000
        )
    )

    assert ledger.payments[result.payment_id].stripe_payment_intent_id == "pi_legacy_1"


@pytest.mark.asyncio
async def test_confirm_rejects_a_charge_already_in_the_ledger() -> None:
    """The deleted queue filtered these out; the guard now lives on confirm."""
    ledger = FakeLedger(invoices={"inv-1": _invoice()})
    ledger.payments["pay-webhook"] = LedgerPayment(
        payment_id="pay-webhook",
        academy_id="acad",
        parent_id="parent-1",
        amount_cents=7_000,
        unapplied_amount_cents=0,
        currency="usd",
        status="succeeded",
        payment_method="card",
        stripe_payment_intent_id="pi_legacy_1",
        paid_at=_NOW,
        created_at=_NOW,
        updated_at=_NOW,
    )

    with pytest.raises(ValueError, match="already recorded"):
        await _uc(ledger).execute(
            ConfirmLegacyMatchCommand(
                invoice_id="inv-1", stripe_charge_id="ch_legacy_1", amount_cents=7_000
            )
        )

    assert len(ledger.allocations) == 0


@pytest.mark.asyncio
async def test_confirm_rejects_an_amount_that_is_not_the_charge_amount() -> None:
    """A typo must not book money nobody paid.

    Typing the invoice balance instead of the charge amount used to pass, since
    the only check was ``amount <= balance``.
    """
    ledger = FakeLedger(invoices={"inv-1": _invoice(total_cents=70_000, balance_due_cents=70_000)})

    with pytest.raises(ValueError, match="does not match the Stripe charge amount"):
        await _uc(ledger, charges=[_charge(amount=7_000)]).execute(
            ConfirmLegacyMatchCommand(
                invoice_id="inv-1", stripe_charge_id="ch_legacy_1", amount_cents=70_000
            )
        )

    assert ledger.payments == {}


@pytest.mark.asyncio
async def test_confirm_rejects_a_charge_belonging_to_another_family() -> None:
    ledger = FakeLedger(invoices={"inv-1": _invoice()})

    with pytest.raises(ValueError, match="not found on this parent"):
        await _uc(ledger, charges=[_charge(charge_id="ch_someone_else")]).execute(
            ConfirmLegacyMatchCommand(
                invoice_id="inv-1", stripe_charge_id="ch_legacy_1", amount_cents=7_000
            )
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("charge", "message"),
    [
        (_charge(refunded=True), "refunded or never paid"),
        (_charge(status="failed"), "did not succeed"),
        (_charge(currency="eur"), "is not in USD"),
    ],
)
async def test_confirm_rejects_a_charge_that_is_not_good_money(
    charge: dict[str, Any], message: str
) -> None:
    ledger = FakeLedger(invoices={"inv-1": _invoice()})

    with pytest.raises(ValueError, match=message):
        await _uc(ledger, charges=[charge]).execute(
            ConfirmLegacyMatchCommand(
                invoice_id="inv-1", stripe_charge_id="ch_legacy_1", amount_cents=7_000
            )
        )


@pytest.mark.asyncio
async def test_confirm_refuses_when_the_parent_has_no_stripe_customer() -> None:
    ledger = FakeLedger(invoices={"inv-1": _invoice()})

    with pytest.raises(ValueError, match="no Stripe customer"):
        await _uc(ledger, customer_id=None).execute(
            ConfirmLegacyMatchCommand(
                invoice_id="inv-1", stripe_charge_id="ch_legacy_1", amount_cents=7_000
            )
        )
