"""Stripe webhook fixture replay.

Replays Stripe-shaped event JSON through `HandleWebhookEvent` and asserts
the resulting domain state. Fixtures live in `stripe_fixtures/` and are
hand-crafted to match the Stripe API shape; in production they should be
swapped for real captures from `stripe trigger <event-type>`.

Coverage:
- checkout.session.completed → Payment(status=succeeded) + outbox PaymentSucceeded
- checkout.session.completed replay (same event_id) → deduped
- checkout.session.expired → Payment(status=expired) + outbox CheckoutExpired
- payment_intent.payment_failed → Payment(status=failed) + outbox PaymentFailed
- charge.refunded partial → refunded_cents updated + status partially_refunded
- charge.refunded full → status refunded
- customer.subscription.updated → dispatch (no-op without seeded subscription)
- customer.subscription.deleted → dispatch (no-op)
- charge.dispute.created → ignored type, returns received without dispatching
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from backend.v2.contexts.billing.application.use_cases.handle_webhook_event import (
    HandleWebhookEvent,
)
from backend.v2.contexts.billing.domain.ledger import InvoiceLine, LedgerInvoice, LedgerPayment
from backend.v2.contexts.billing.domain.models import Payment, Subscription
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import (
    FakeStripeGateway,
)

FIXTURES = Path(__file__).parent / "stripe_fixtures"


def _load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class FakePaymentRepo:
    def __init__(self):
        self.by_id: dict[str, Payment] = {}
        self.by_checkout: dict[str, Payment] = {}
        self.by_pi: dict[str, Payment] = {}

    def seed(self, p: Payment) -> None:
        self.by_id[p.payment_id] = p
        if p.stripe_checkout_session_id:
            self.by_checkout[p.stripe_checkout_session_id] = p
        if p.stripe_payment_intent_id:
            self.by_pi[p.stripe_payment_intent_id] = p

    async def save(self, p):
        self.seed(p)

    async def get(self, pid):
        return self.by_id.get(pid)

    async def get_by_stripe_pi(self, pi):
        return self.by_pi.get(pi)

    async def get_by_checkout_session(self, sid):
        return self.by_checkout.get(sid)

    async def list_for_parent(self, _):
        return list(self.by_id.values())


class FakeSubscriptionRepo:
    def __init__(self) -> None:
        self.by_stripe_sub: dict[str, Subscription] = {}

    def seed(self, subscription: Subscription) -> None:
        self.by_stripe_sub[subscription.stripe_subscription_id] = subscription

    async def save(self, _):
        self.seed(_)

    async def get(self, _):
        return None

    async def get_by_stripe_sub(self, stripe_sub):
        return self.by_stripe_sub.get(stripe_sub)

    async def latest_for_enrollment(self, _):
        return None


class FakeDedup:
    def __init__(self) -> None:
        self.claimed: set[str] = set()

    async def claim(self, event_id, _type):
        if event_id in self.claimed:
            return False
        self.claimed.add(event_id)
        return True

    async def mark_processed(self, _):
        pass

    async def mark_failed(self, _, __):
        pass


class FakeOutbox:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def append(self, event, *, session=None):
        self.events.append(event)

    async def pull_unprocessed(self, _limit=100):
        return []

    async def mark_processed(self, _):
        pass


def _build(repo, outbox=None, dedup=None):
    return HandleWebhookEvent(
        stripe=FakeStripeGateway(),
        dedup=dedup or FakeDedup(),
        payments=repo,
        subscriptions=FakeSubscriptionRepo(),
        outbox=outbox or FakeOutbox(),
        academy_id="test-academy",
    )


def _seed_pending(
    repo: FakePaymentRepo,
    *,
    payment_id: str,
    checkout_id: str | None = None,
    pi: str | None = None,
    status: str = "pending",
):
    now = datetime.now(UTC)
    p = Payment(
        payment_id=payment_id,
        academy_id="test-academy",
        parent_id=f"parent-{payment_id}",
        session_id=f"sess-{payment_id}",
        stripe_checkout_session_id=checkout_id,
        stripe_payment_intent_id=pi,
        amount_cents=15000,
        status=status,  # type: ignore[arg-type]
        created_at=now,
        updated_at=now,
    )
    repo.seed(p)
    return p


# ---------------------------------------------------------------------------
# checkout.session.completed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fixture_checkout_completed_marks_succeeded() -> None:
    repo = FakePaymentRepo()
    _seed_pending(repo, payment_id="pay-001", checkout_id="cs_test_abcdef0000000001")
    outbox = FakeOutbox()
    uc = _build(repo, outbox=outbox)
    res = await uc.execute(_load("checkout_session_completed.json"), "test_signature")
    assert res["received"] is True
    assert repo.by_id["pay-001"].status == "succeeded"
    assert repo.by_id["pay-001"].stripe_payment_intent_id == "pi_test_0000000001"
    assert [e.name for e in outbox.events] == ["Billing.PaymentSucceeded"]
    succeeded = outbox.events[0]
    assert succeeded.payload.amount_cents == 15000
    assert succeeded.payload.session_id == "sess-pay-001"


@pytest.mark.asyncio
async def test_fixture_checkout_completed_dedupe_on_replay() -> None:
    repo = FakePaymentRepo()
    _seed_pending(repo, payment_id="pay-001", checkout_id="cs_test_abcdef0000000001")
    outbox = FakeOutbox()
    dedup = FakeDedup()
    uc = _build(repo, outbox=outbox, dedup=dedup)
    first = await uc.execute(_load("checkout_session_completed.json"), "test_signature")
    second = await uc.execute(_load("checkout_session_completed_duplicate.json"), "test_signature")
    assert first.get("type") == "checkout.session.completed"
    assert second.get("deduped") is True
    # Only one PaymentSucceeded emitted despite two webhook calls.
    assert sum(1 for e in outbox.events if e.name == "Billing.PaymentSucceeded") == 1


# ---------------------------------------------------------------------------
# checkout.session.expired
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fixture_checkout_expired_transitions_pending_to_expired() -> None:
    repo = FakePaymentRepo()
    _seed_pending(repo, payment_id="pay-002", checkout_id="cs_test_abcdef0000000002")
    outbox = FakeOutbox()
    uc = _build(repo, outbox=outbox)
    res = await uc.execute(_load("checkout_session_expired.json"), "test_signature")
    assert res["received"] is True
    assert repo.by_id["pay-002"].status == "expired"
    assert outbox.events[0].name == "Billing.CheckoutExpired"


# ---------------------------------------------------------------------------
# payment_intent.payment_failed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fixture_payment_failed_marks_failed_with_reason() -> None:
    repo = FakePaymentRepo()
    _seed_pending(repo, payment_id="pay-003", pi="pi_test_0000000003")
    outbox = FakeOutbox()
    uc = _build(repo, outbox=outbox)
    await uc.execute(_load("payment_intent_payment_failed.json"), "test_signature")
    assert repo.by_id["pay-003"].status == "failed"
    failed = outbox.events[0]
    assert failed.name == "Billing.PaymentFailed"
    assert "declined" in failed.payload.reason.lower()


# ---------------------------------------------------------------------------
# charge.refunded
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fixture_charge_refunded_partial_marks_partially_refunded() -> None:
    repo = FakePaymentRepo()
    _seed_pending(repo, payment_id="pay-004", pi="pi_test_0000000004", status="succeeded")
    outbox = FakeOutbox()
    uc = _build(repo, outbox=outbox)
    await uc.execute(_load("charge_refunded_partial.json"), "test_signature")
    assert repo.by_id["pay-004"].refunded_cents == 5000
    assert repo.by_id["pay-004"].status == "partially_refunded"
    refunded = outbox.events[0]
    assert refunded.name == "Billing.PaymentRefunded"
    assert refunded.payload.total_refunded_cents == 5000


@pytest.mark.asyncio
async def test_fixture_charge_refunded_full_marks_refunded() -> None:
    repo = FakePaymentRepo()
    _seed_pending(repo, payment_id="pay-005", pi="pi_test_0000000005", status="succeeded")
    outbox = FakeOutbox()
    uc = _build(repo, outbox=outbox)
    await uc.execute(_load("charge_refunded_full.json"), "test_signature")
    assert repo.by_id["pay-005"].refunded_cents == 15000
    assert repo.by_id["pay-005"].status == "refunded"


# ---------------------------------------------------------------------------
# customer.subscription.updated / deleted (no-op without seeded subscription)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fixture_subscription_updated_skipped_when_unknown_subscription() -> None:
    repo = FakePaymentRepo()
    outbox = FakeOutbox()
    uc = _build(repo, outbox=outbox)
    # Subscription repo is a fake that returns None — no state change, no event.
    res = await uc.execute(_load("customer_subscription_updated.json"), "test_signature")
    assert res["received"] is True
    assert outbox.events == []


@pytest.mark.asyncio
async def test_fixture_subscription_deleted_skipped_when_unknown_subscription() -> None:
    repo = FakePaymentRepo()
    outbox = FakeOutbox()
    uc = _build(repo, outbox=outbox)
    res = await uc.execute(_load("customer_subscription_deleted.json"), "test_signature")
    assert res["received"] is True
    assert outbox.events == []


# ---------------------------------------------------------------------------
# Unknown / ignored event types
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fixture_charge_dispute_created_is_ignored() -> None:
    """Legacy didn't handle disputes; v2 currently ignores them too.
    If the product later needs dispute handling, this test will need
    updating + a new handler in HandleWebhookEvent._dispatch.
    """
    repo = FakePaymentRepo()
    outbox = FakeOutbox()
    uc = _build(repo, outbox=outbox)
    res = await uc.execute(_load("charge_dispute_created.json"), "test_signature")
    assert res["received"] is True
    assert outbox.events == []


# ---------------------------------------------------------------------------
# Fixture sanity — make sure every JSON parses + has the required shape.
# ---------------------------------------------------------------------------


def test_all_fixtures_parse() -> None:
    for path in FIXTURES.glob("*.json"):
        body = json.loads(path.read_text())
        assert "id" in body
        assert "type" in body
        assert "data" in body
        assert "object" in body["data"]


# ---------------------------------------------------------------------------
# checkout.session.completed with source=invoice_pay_link
# ---------------------------------------------------------------------------


class FakeBillingLedger:
    """Minimal billing ledger double for pay-link webhook tests."""

    def __init__(self) -> None:
        self.invoices: dict[str, LedgerInvoice] = {}
        self.lines: dict[str, list[InvoiceLine]] = {}
        self.payments: dict[str, LedgerPayment] = {}
        self.payment_keys: dict[str, str] = {}
        self.allocation_keys: set[str] = set()
        self.allocations: list[dict[str, Any]] = []
        self.payment_attempts: dict[str, dict[str, Any]] = {}
        self.fail_allocate = False

    async def create_invoice(
        self,
        invoice: LedgerInvoice,
        *,
        lines: list[InvoiceLine],
        idempotency_key: str,
    ) -> LedgerInvoice:
        self.invoices[invoice.invoice_id] = invoice
        self.lines[invoice.invoice_id] = lines
        return invoice

    async def get_invoice(self, invoice_id: str) -> LedgerInvoice | None:
        return self.invoices.get(invoice_id)

    async def get_invoice_by_stripe_invoice_id(
        self, stripe_invoice_id: str
    ) -> LedgerInvoice | None:
        for invoice in self.invoices.values():
            if invoice.stripe_invoice_id == stripe_invoice_id:
                return invoice
        return None

    async def get_invoice_for_enrollment_period(
        self,
        enrollment_id: str,
        period: str,
        *,
        statuses: set[str] | None = None,
    ) -> LedgerInvoice | None:
        for invoice in self.invoices.values():
            if invoice.enrollment_id != enrollment_id or invoice.period != period:
                continue
            if statuses is not None and invoice.status not in statuses:
                continue
            return invoice
        return None

    async def get_open_invoice_for_enrollment(
        self, enrollment_id: str, period: str
    ) -> LedgerInvoice | None:
        return await self.get_invoice_for_enrollment_period(
            enrollment_id,
            period,
            statuses={"draft", "open", "partially_paid"},
        )

    async def get_open_invoice_for_student(
        self, student_id: str, period: str
    ) -> LedgerInvoice | None:
        for invoice in self.invoices.values():
            if (
                invoice.student_id == student_id
                and invoice.period == period
                and invoice.status in {"draft", "open", "partially_paid"}
            ):
                return invoice
        return None

    async def save_invoice(self, invoice: LedgerInvoice) -> LedgerInvoice:
        self.invoices[invoice.invoice_id] = invoice
        return invoice

    async def record_payment(
        self, payment: LedgerPayment, *, idempotency_key: str
    ) -> LedgerPayment:
        existing_id = self.payment_keys.get(idempotency_key)
        if existing_id is not None:
            return self.payments[existing_id]
        self.payments[payment.payment_id] = payment
        self.payment_keys[idempotency_key] = payment.payment_id
        return payment

    async def allocate_payment(
        self,
        *,
        payment_id: str,
        invoice_id: str,
        amount_cents: int,
        idempotency_key: str,
    ) -> None:
        if self.fail_allocate:
            raise ValueError("allocation failed")
        if idempotency_key in self.allocation_keys:
            return None
        if invoice_id in self.invoices and payment_id in self.payments:
            invoice = self.invoices[invoice_id]
            payment = self.payments[payment_id]
            allocated = min(amount_cents, invoice.balance_due_cents)
            self.invoices[invoice_id] = invoice.model_copy(
                update={
                    "balance_due_cents": max(invoice.balance_due_cents - allocated, 0),
                    "status": "paid"
                    if invoice.balance_due_cents - allocated <= 0
                    else "partially_paid",
                }
            )
            self.payments[payment_id] = payment.model_copy(
                update={
                    "unapplied_amount_cents": max(
                        payment.unapplied_amount_cents - allocated,
                        0,
                    ),
                }
            )
        self.allocation_keys.add(idempotency_key)
        self.allocations.append(
            {
                "payment_id": payment_id,
                "invoice_id": invoice_id,
                "amount_cents": amount_cents,
                "idempotency_key": idempotency_key,
            }
        )

    async def get_payment_allocation_by_idempotency_key(
        self, idempotency_key: str
    ) -> dict[str, Any] | None:
        for allocation in self.allocations:
            if allocation["idempotency_key"] == idempotency_key:
                return allocation
        return None

    async def get_payment_by_stripe_payment_intent_id(
        self, stripe_payment_intent_id: str
    ) -> LedgerPayment | None:
        for payment in self.payments.values():
            if payment.stripe_payment_intent_id == stripe_payment_intent_id:
                return payment
        return None

    async def mark_payment_refunded(
        self,
        payment_id: str,
        *,
        refunded_cents: int,
        status: str,
        updated_at: datetime,
    ) -> LedgerPayment:
        payment = self.payments[payment_id]
        updated = payment.model_copy(
            update={
                "refunded_cents": refunded_cents,
                "status": status,
                "updated_at": updated_at,
            }
        )
        self.payments[payment_id] = updated
        return updated

    async def record_payment_attempt(
        self,
        *,
        invoice_id: str,
        parent_id: str,
        amount_cents: int,
        currency: str,
        status: str,
        stripe_payment_intent_id: str | None,
        stripe_checkout_session_id: str | None,
        failure_code: str | None,
        failure_message: str | None,
        idempotency_key: str,
        created_by_event_id: str | None = None,
    ) -> dict[str, Any]:
        attempt = self.payment_attempts.get(idempotency_key)
        if attempt is not None:
            return attempt
        attempt = {
            "invoice_id": invoice_id,
            "parent_id": parent_id,
            "amount_cents": amount_cents,
            "currency": currency,
            "status": status,
            "stripe_payment_intent_id": stripe_payment_intent_id,
            "stripe_checkout_session_id": stripe_checkout_session_id,
            "failure_code": failure_code,
            "failure_message": failure_message,
            "idempotency_key": idempotency_key,
            "created_by_event_id": created_by_event_id,
        }
        self.payment_attempts[idempotency_key] = attempt
        return attempt

    async def reverse_payment_allocation(
        self,
        *,
        allocation_idempotency_key: str,
        reversal_idempotency_key: str,
        reason: str,
        return_code: str | None,
        reversed_at: datetime,
    ) -> dict[str, Any] | None:
        for allocation in list(self.allocations):
            if allocation["idempotency_key"] != allocation_idempotency_key:
                continue
            invoice = self.invoices[allocation["invoice_id"]]
            payment = self.payments[allocation["payment_id"]]
            self.allocations.remove(allocation)
            self.allocation_keys.discard(allocation_idempotency_key)
            self.invoices[invoice.invoice_id] = invoice.model_copy(
                update={
                    "status": "open",
                    "balance_due_cents": invoice.total_cents,
                    "updated_at": reversed_at,
                }
            )
            self.payments[payment.payment_id] = payment.model_copy(
                update={"unapplied_amount_cents": 0, "updated_at": reversed_at}
            )
            return {
                "payment_id": payment.payment_id,
                "invoice_id": invoice.invoice_id,
                "amount_cents": allocation["amount_cents"],
                "reason": reason,
                "return_code": return_code,
                "idempotency_key": reversal_idempotency_key,
            }
        return None


def _build_with_ledger(repo, ledger, outbox=None, dedup=None, subscriptions=None):
    return HandleWebhookEvent(
        stripe=FakeStripeGateway(),
        dedup=dedup or FakeDedup(),
        payments=repo,
        subscriptions=subscriptions or FakeSubscriptionRepo(),
        outbox=outbox or FakeOutbox(),
        academy_id="test-academy",
        billing_ledger=ledger,
    )


def _seed_autopay_invoice(ledger: FakeBillingLedger) -> None:
    now = datetime(2026, 6, 17, 12, 0, tzinfo=UTC)
    ledger.invoices["inv-ach-fixture-01"] = LedgerInvoice(
        invoice_id="inv-ach-fixture-01",
        academy_id="test-academy",
        parent_id="parent-ach-fixture",
        student_id="student-ach-fixture",
        enrollment_id="enr-ach-fixture",
        period="2026-06",
        status="open",
        subtotal_cents=10_000,
        discount_cents=0,
        total_cents=10_000,
        balance_due_cents=10_000,
        currency="usd",
        due_date=date(2026, 6, 30),
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_fixture_autopay_ach_processing_records_attempt_without_allocation() -> None:
    repo = FakePaymentRepo()
    ledger = FakeBillingLedger()
    _seed_autopay_invoice(ledger)
    uc = _build_with_ledger(repo, ledger)

    res = await uc.execute(_load("payment_intent_processing_ach_autopay.json"), "test_signature")

    assert res["received"] is True
    invoice = ledger.invoices["inv-ach-fixture-01"]
    assert invoice.status == "open"
    assert invoice.balance_due_cents == 10_000
    assert ledger.payments == {}
    assert ledger.allocations == []
    assert next(iter(ledger.payment_attempts.values()))["status"] == "processing"


@pytest.mark.asyncio
async def test_fixture_autopay_ach_succeeded_allocates_after_settlement() -> None:
    repo = FakePaymentRepo()
    ledger = FakeBillingLedger()
    _seed_autopay_invoice(ledger)
    uc = _build_with_ledger(repo, ledger)

    res = await uc.execute(_load("payment_intent_succeeded_ach_autopay.json"), "test_signature")

    assert res["received"] is True
    invoice = ledger.invoices["inv-ach-fixture-01"]
    assert invoice.status == "paid"
    assert invoice.balance_due_cents == 0
    payment = ledger.payments["ledger-pay-autopay:pi_ach_fixture_01"]
    assert payment.metadata == {"funding_type": "us_bank_account"}
    assert ledger.allocations[0]["idempotency_key"] == "autopay-alloc:pi_ach_fixture_01"


@pytest.mark.asyncio
async def test_fixture_autopay_ach_return_reopens_paid_invoice() -> None:
    repo = FakePaymentRepo()
    ledger = FakeBillingLedger()
    _seed_autopay_invoice(ledger)
    outbox = FakeOutbox()
    uc = _build_with_ledger(repo, ledger, outbox=outbox)

    await uc.execute(_load("payment_intent_succeeded_ach_autopay.json"), "test_signature")
    res = await uc.execute(_load("charge_refunded_ach_return.json"), "test_signature")

    assert res["received"] is True
    invoice = ledger.invoices["inv-ach-fixture-01"]
    payment = ledger.payments["ledger-pay-autopay:pi_ach_fixture_01"]
    assert invoice.status == "open"
    assert invoice.balance_due_cents == 10_000
    assert payment.status == "refunded"
    assert payment.refunded_cents == 10_000
    assert ledger.allocations == []
    returned_attempt = next(
        attempt for attempt in ledger.payment_attempts.values() if attempt["status"] == "returned"
    )
    assert returned_attempt["failure_code"] == "R01"
    assert outbox.events[-1].name == "Billing.PaymentRefunded"


@pytest.mark.asyncio
async def test_fixture_invoice_pay_link_checkout_records_ledger_payment_and_allocates() -> None:
    """checkout.session.completed with source=invoice_pay_link creates a
    LedgerPayment in ledger_payments and calls allocate_payment."""
    repo = FakePaymentRepo()
    ledger = FakeBillingLedger()
    uc = _build_with_ledger(repo, ledger)

    res = await uc.execute(
        _load("checkout_session_completed_invoice_pay_link.json"), "test_signature"
    )

    assert res["received"] is True

    # One LedgerPayment must be recorded
    assert len(ledger.payments) == 1
    (lp,) = ledger.payments.values()
    assert lp.payment_id == "ledger-pay-cs:cs_test_abcdef0000000099"
    assert lp.amount_cents == 20000
    assert lp.status == "succeeded"
    assert lp.payment_method == "stripe_checkout"
    assert lp.stripe_payment_intent_id == "pi_test_0000000099"
    assert lp.parent_id == "parent-099"

    # allocate_payment must have been called for the correct invoice
    assert len(ledger.allocations) == 1
    alloc = ledger.allocations[0]
    assert alloc["invoice_id"] == "inv-pay-link-test-01"
    assert alloc["amount_cents"] == 20000
    assert alloc["payment_id"] == lp.payment_id


@pytest.mark.asyncio
async def test_fixture_subscription_invoice_paid_api_2026_converges_ledger() -> None:
    repo = FakePaymentRepo()
    ledger = FakeBillingLedger()
    now = datetime(2026, 6, 17, 12, 0, tzinfo=UTC)
    subscriptions = FakeSubscriptionRepo()
    subscriptions.seed(
        Subscription(
            subscription_id="sub-local-1",
            academy_id="test-academy",
            parent_id="parent-1",
            enrollment_id="enr-1",
            session_id="session-1",
            stripe_subscription_id="sub_subscription_api_2026",
            status="active",
            created_at=now,
            updated_at=now,
        )
    )
    ledger.invoices["inv-monthly-enr-1-2026-06"] = LedgerInvoice(
        invoice_id="inv-monthly-enr-1-2026-06",
        academy_id="test-academy",
        parent_id="parent-1",
        student_id="student-1",
        enrollment_id="enr-1",
        period="2026-06",
        status="open",
        subtotal_cents=7_000,
        discount_cents=0,
        total_cents=7_000,
        balance_due_cents=7_000,
        currency="usd",
        due_date=date(2026, 6, 30),
        created_at=now,
        updated_at=now,
    )
    uc = _build_with_ledger(repo, ledger, subscriptions=subscriptions)

    res = await uc.execute(
        _load("invoice_paid_subscription_api_2026.json"),
        "test_signature",
    )

    assert res["received"] is True
    invoice = ledger.invoices["inv-monthly-enr-1-2026-06"]
    assert invoice.status == "paid"
    assert invoice.balance_due_cents == 0
    assert invoice.stripe_invoice_id == "in_subscription_api_2026"
    assert len(ledger.payments) == 1
    assert len(ledger.allocations) == 1
    assert len(repo.by_id) == 1
    payment = ledger.payments["ledger-pay-in_subscription_api_2026"]
    assert payment.stripe_payment_intent_id == "in_subscription_api_2026"
    assert payment.stripe_invoice_id == "in_subscription_api_2026"


@pytest.mark.asyncio
async def test_invoice_pay_link_allocation_failure_is_retryable() -> None:
    repo = FakePaymentRepo()
    ledger = FakeBillingLedger()
    ledger.fail_allocate = True
    uc = _build_with_ledger(repo, ledger)

    with pytest.raises(ValueError, match="allocation failed"):
        await uc.execute(
            _load("checkout_session_completed_invoice_pay_link.json"), "test_signature"
        )

    assert len(ledger.payments) == 1
    assert ledger.allocations == []
