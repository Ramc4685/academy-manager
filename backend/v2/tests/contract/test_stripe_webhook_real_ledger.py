"""Stripe webhook replay against the real ledger on a real mongod.

The ACH receipt, admin charge-now settlement and dispute tests used to run on
``FakeBillingLedger`` in test_stripe_webhook_fixture_replay.py, which does not
enforce the ledger's real refusals (partial unique indexes, allocation claims,
validators). They run here on ``real_db`` with ``MongoBillingLedgerRepository``
and ``MongoPaymentDisputeRepository``; the outbox, dedup and legacy payment
repo stay as the fixture file's doubles, since they are not under test. The
move already paid off once: the fake let a pay-link payment allocate to another
parent's invoice, which the real ledger refuses.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

import pytest

from backend.v2.contexts.billing.application.use_cases.handle_webhook_event import (
    HandleWebhookEvent,
)
from backend.v2.contexts.billing.domain.ledger import InvoiceLine, LedgerInvoice
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import FakeStripeGateway
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_payment_dispute_repo import (
    MongoPaymentDisputeRepository,
)
from backend.v2.tests.contract.test_stripe_webhook_fixture_replay import (
    FakeDedup,
    FakeOutbox,
    FakePaymentRepo,
    FakeSubscriptionRepo,
    _load,
)

pytestmark = pytest.mark.asyncio

ACH_INVOICE = "inv-ach-fixture-01"
PAY_LINK_INVOICE = "inv-pay-link-test-01"


class _FamilyPause:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    async def pause_family(
        self, *, academy_id: str, parent_id: str, reason: str, request_id: str
    ) -> int:
        self.calls.append({"parent_id": parent_id, "reason": reason, "request_id": request_id})
        return 1


async def _seed_invoice(
    ledger: MongoBillingLedgerRepository,
    invoice_id: str,
    cents: int,
    parent_id: str = "parent-ach-fixture",
) -> None:
    now = datetime(2026, 6, 17, 12, 0, tzinfo=UTC)
    invoice = LedgerInvoice(
        invoice_id=invoice_id,
        academy_id="test-academy",
        parent_id=parent_id,
        student_id="student-ach-fixture",
        enrollment_id="enr-ach-fixture",
        period="2026-06",
        status="open",
        subtotal_cents=cents,
        discount_cents=0,
        total_cents=cents,
        balance_due_cents=cents,
        currency="usd",
        due_date=date(2026, 6, 30),
        created_at=now,
        updated_at=now,
    )
    line = InvoiceLine(
        line_id=f"{invoice_id}-tuition",
        academy_id="test-academy",
        invoice_id=invoice_id,
        line_type="tuition",
        description="June tuition",
        quantity=1,
        unit_amount_cents=cents,
        amount_cents=cents,
        created_at=now,
    )
    await ledger.create_invoice(invoice, lines=[line], idempotency_key=f"seed:{invoice_id}")


def _handler(real_db, outbox: FakeOutbox, family: _FamilyPause | None = None) -> HandleWebhookEvent:
    return HandleWebhookEvent(
        stripe=FakeStripeGateway(),
        dedup=FakeDedup(),
        payments=FakePaymentRepo(),
        subscriptions=FakeSubscriptionRepo(),
        outbox=outbox,
        academy_id="test-academy",
        billing_ledger=MongoBillingLedgerRepository(real_db),
        payment_disputes=MongoPaymentDisputeRepository(real_db),
        family_autopay=family or _FamilyPause(),
    )


def _dispute_payload(
    event_id: str, pi_id: str, *, amount: int, reason: str = "fraudulent"
) -> bytes:
    return json.dumps(
        {
            "id": event_id,
            "type": "charge.dispute.closed",
            "livemode": False,
            "data": {
                "object": {
                    "id": f"dp_{event_id}",
                    "object": "dispute",
                    "amount": amount,
                    "currency": "usd",
                    "payment_intent": pi_id,
                    "reason": reason,
                    "status": "lost",
                }
            },
        }
    ).encode()


async def _invoice(real_db, invoice_id: str) -> dict[str, Any]:
    doc = await real_db["invoices"].find_one(
        {"academy_id": "test-academy", "invoice_id": invoice_id}
    )
    assert doc is not None
    return doc


async def test_settled_bank_debit_requests_one_receipt_per_payment(real_db, acad) -> None:
    """L1 A5-2: the receipt comes from the settle webhook, keyed by payment id."""
    await _seed_invoice(MongoBillingLedgerRepository(real_db), ACH_INVOICE, 10_000)
    outbox = FakeOutbox()
    uc = _handler(real_db, outbox)

    await uc.execute(_load("payment_intent_succeeded_ach_autopay.json"), "test_signature")
    # A redelivery of the same settlement must not mint a second receipt.
    await uc.execute(_load("payment_intent_succeeded_ach_autopay.json"), "test_signature")

    receipts = [e for e in outbox.events if e.name == "Billing.PaymentReceiptRequested"]
    assert len(receipts) == 1
    receipt = receipts[0]
    assert receipt.event_id == "payment-receipt:ledger-pay-autopay:pi_ach_fixture_01"
    assert receipt.payload.bank_debit is True
    assert receipt.payload.autopay is True
    assert receipt.payload.invoice_id == ACH_INVOICE
    assert receipt.payload.amount_cents == 10_000


@pytest.mark.parametrize("source", ["admin_manual", "admin_billing_setup"])
async def test_admin_charge_now_bank_debit_settles_the_invoice(real_db, acad, source) -> None:
    """L1: an admin "charge now" bank debit is the same off-session PaymentIntent as
    autopay; its settlement must close the invoice, not fall to the legacy path."""
    await _seed_invoice(MongoBillingLedgerRepository(real_db), ACH_INVOICE, 10_000)
    event = json.loads(_load("payment_intent_succeeded_ach_autopay.json"))
    event["data"]["object"]["metadata"]["source"] = source

    await _handler(real_db, FakeOutbox()).execute(json.dumps(event).encode(), "test_signature")

    invoice = await _invoice(real_db, ACH_INVOICE)
    assert invoice["status"] == "paid"
    assert invoice["balance_due_cents"] == 0


async def test_lost_dispute_reopens_a_checkout_paid_invoice_and_pauses_the_family(
    real_db, acad
) -> None:
    """L1 B3/B4: a pay-link payment is reversed through its own allocations, and
    the whole family's autopay pauses, not only one enrollment."""
    await _seed_invoice(
        MongoBillingLedgerRepository(real_db), PAY_LINK_INVOICE, 20_000, "parent-099"
    )
    family = _FamilyPause()
    outbox = FakeOutbox()
    uc = _handler(real_db, outbox, family)
    await uc.execute(_load("checkout_session_completed_invoice_pay_link.json"), "test_signature")
    assert (await _invoice(real_db, PAY_LINK_INVOICE))["status"] == "paid"
    payment = await real_db["ledger_payments"].find_one({"academy_id": "test-academy"})
    assert payment is not None

    await uc.execute(
        _dispute_payload(
            "evt_d_checkout", payment["stripe_payment_intent_id"], amount=payment["amount_cents"]
        ),
        "test_signature",
    )

    payment = await real_db["ledger_payments"].find_one({"payment_id": payment["payment_id"]})
    assert payment["status"] == "refunded"
    assert await real_db["payment_allocations"].count_documents({}) == 0
    assert (await _invoice(real_db, PAY_LINK_INVOICE))["status"] == "open"
    assert [c["parent_id"] for c in family.calls] == [payment["parent_id"]]
    # A card dispute is the parent's own claim: no "payment returned" notice.
    assert "Billing.DunningNoticeRequested" not in [e.name for e in outbox.events]


async def test_bank_return_filed_as_a_dispute_tells_the_parent(real_db, acad) -> None:
    """L1 should-fix 1: insufficient funds arriving as a dispute is a bank return."""
    await _seed_invoice(MongoBillingLedgerRepository(real_db), ACH_INVOICE, 10_000)
    outbox = FakeOutbox()
    uc = _handler(real_db, outbox)
    await uc.execute(_load("payment_intent_succeeded_ach_autopay.json"), "test_signature")

    await uc.execute(
        _dispute_payload(
            "evt_d_nsf", "pi_ach_fixture_01", amount=10_000, reason="insufficient_funds"
        ),
        "test_signature",
    )

    notice = next(e for e in outbox.events if e.name == "Billing.DunningNoticeRequested")
    assert notice.payload.failure_code == "dispute:insufficient_funds"
    assert notice.payload.balance_due_cents == 10_000
    assert (await _invoice(real_db, ACH_INVOICE))["status"] == "open"


async def test_partial_lost_dispute_pauses_autopay_without_reversing(real_db, acad) -> None:
    await _seed_invoice(MongoBillingLedgerRepository(real_db), ACH_INVOICE, 10_000)
    family = _FamilyPause()
    uc = _handler(real_db, FakeOutbox(), family)
    await uc.execute(_load("payment_intent_succeeded_ach_autopay.json"), "test_signature")

    await uc.execute(
        _dispute_payload("evt_d_part", "pi_ach_fixture_01", amount=4_000), "test_signature"
    )

    assert (await _invoice(real_db, ACH_INVOICE))["status"] == "paid"
    assert family.calls and family.calls[0]["request_id"] == "payment-return:pi_ach_fixture_01"
    codes = [a.get("failure_code") async for a in real_db["payment_attempts"].find({})]
    assert "unsupported_partial_ach_return" in codes
