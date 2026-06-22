"""Admin billing + finance BFF — happy + wrong-persona 404."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from backend.v2.composition.admin import _InvoiceEmailAdapter
from backend.v2.contexts.billing.application.use_cases.add_invoice_line import (
    AddInvoiceLine,
    AddInvoiceLineCommand,
)
from backend.v2.contexts.billing.application.use_cases.finance import Payout
from backend.v2.contexts.billing.application.use_cases.remove_invoice_line import (
    RemoveInvoiceLine,
    RemoveInvoiceLineCommand,
)
from backend.v2.contexts.billing.application.use_cases.send_invoice import SendInvoice
from backend.v2.contexts.billing.domain import ledger as ledger_domain
from backend.v2.contexts.billing.domain.ledger import InvoiceLine, LedgerInvoice
from backend.v2.contexts.billing.domain.models import Payment
from backend.v2.contexts.communications.application.ports import SendOutcome
from backend.v2.contexts.enrollment.application.use_cases.admin_directory import (
    AdminStudentDetail,
    AdminStudentSessionSummary,
)
from backend.v2.contexts.identity.domain.models import AcademyMembership, User
from backend.v2.shared.tenancy import tenant_scope


def _seed_payment(
    seed,
    payment_id: str,
    amount_cents: int = 15000,
    status: str = "succeeded",
    stripe: bool = True,
):
    now = datetime.now(UTC)
    seed["payments"].rows[payment_id] = Payment(
        payment_id=payment_id,
        academy_id="acad",
        parent_id=f"parent-{payment_id}",
        session_id="sess-1",
        stripe_payment_intent_id=f"pi_{payment_id}" if stripe else None,
        amount_cents=amount_cents,
        currency="usd",
        status=status,  # type: ignore[arg-type]
        refunded_cents=0,
        created_at=now,
        updated_at=now,
    )


NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def _invoice(
    *,
    invoice_id: str = "inv-1",
    status: str = "draft",
    subtotal_cents: int = 7_000,
    total_cents: int = 7_000,
    balance_due_cents: int = 7_000,
) -> LedgerInvoice:
    return LedgerInvoice(
        invoice_id=invoice_id,
        academy_id="acad",
        parent_id="parent-1",
        student_id="student-1",
        enrollment_id="enroll-1",
        period="2026-06",
        status=status,  # type: ignore[arg-type]
        subtotal_cents=subtotal_cents,
        discount_cents=0,
        total_cents=total_cents,
        balance_due_cents=balance_due_cents,
        currency="usd",
        due_date=date(2026, 6, 30),
        created_at=NOW,
        updated_at=NOW,
    )


def _invoice_line(
    *,
    line_id: str,
    invoice_id: str = "inv-1",
    amount_cents: int,
    description: str = "Line item",
) -> InvoiceLine:
    return InvoiceLine(
        line_id=line_id,
        academy_id="acad",
        invoice_id=invoice_id,
        line_type="fee",
        description=description,
        quantity=1,
        unit_amount_cents=amount_cents,
        amount_cents=amount_cents,
        created_at=NOW,
    )


class _FakeLedger:
    def __init__(
        self,
        *,
        invoices: list[LedgerInvoice] | None = None,
        lines: list[InvoiceLine] | None = None,
    ) -> None:
        self.invoices = {invoice.invoice_id: invoice for invoice in invoices or []}
        self.lines = {line.line_id: line for line in lines or []}
        self.saved_invoices: list[LedgerInvoice] = []

    async def get_invoice(self, invoice_id: str) -> LedgerInvoice | None:
        return self.invoices.get(invoice_id)

    async def get_open_invoice_for_student(
        self, student_id: str, period: str
    ) -> LedgerInvoice | None:
        for invoice in self.invoices.values():
            if invoice.student_id == student_id and invoice.period == period:
                return invoice
        return None

    async def get_lines_for_invoice(self, invoice_id: str) -> list[InvoiceLine]:
        return [line for line in self.lines.values() if line.invoice_id == invoice_id]

    async def save_invoice(self, invoice: LedgerInvoice) -> LedgerInvoice:
        self.invoices[invoice.invoice_id] = invoice
        self.saved_invoices.append(invoice)
        return invoice

    async def save_line(self, line: InvoiceLine) -> InvoiceLine:
        self.lines[line.line_id] = line
        return line

    async def create_invoice(
        self,
        invoice: LedgerInvoice,
        *,
        lines: list[InvoiceLine],
        idempotency_key: str,
    ) -> LedgerInvoice:
        self.invoices[invoice.invoice_id] = invoice
        for line in lines:
            self.lines[line.line_id] = line
        return invoice

    async def delete_invoice_line(self, *, invoice_id: str, line_id: str) -> bool:
        line = self.lines.get(line_id)
        if line is None or line.invoice_id != invoice_id:
            return False
        del self.lines[line_id]
        return True


class _FakeGetAdminStudent:
    def __init__(self, student: AdminStudentDetail | None) -> None:
        self.student = student

    async def execute(self, student_id: str) -> AdminStudentDetail:
        from backend.v2.contexts.enrollment.domain.errors import StudentNotFound

        if self.student is None or self.student.student_id != student_id:
            raise StudentNotFound("student not found")
        return self.student


class _FakeInvoiceStripe:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def create_invoice_checkout_session(self, **kwargs) -> tuple[str, str]:
        self.calls.append(kwargs)
        return "cs_invoice_test", "https://checkout.stripe.test/invoice"


class _FakeInvoiceEmail:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def send_invoice_email(self, **kwargs) -> None:
        self.calls.append(kwargs)


class _FakeEmailSender:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def send(self, **kwargs) -> SendOutcome:
        self.calls.append(kwargs)
        return SendOutcome(ok=True, provider_message_id="msg_test", failed_reason=None)


class _FakeMembershipRepo:
    def __init__(self, membership: AcademyMembership | None) -> None:
        self.membership = membership
        self.calls: list[tuple[str, str]] = []

    async def get_membership(self, academy_id: str, user_id: str) -> AcademyMembership | None:
        self.calls.append((academy_id, user_id))
        if (
            self.membership is not None
            and self.membership.academy_id == academy_id
            and self.membership.user_id == user_id
        ):
            return self.membership
        return None


class _FakeUserRepo:
    def __init__(self, user: User | None) -> None:
        self.user = user
        self.calls: list[str] = []

    async def get_by_id(self, user_id: str) -> User | None:
        self.calls.append(user_id)
        if self.user is not None and self.user.user_id == user_id:
            return self.user
        return None


def _student_detail(
    *,
    student_id: str = "student-1",
    parent_id: str = "parent-1",
    enrollment_ids: list[str] | None = None,
) -> AdminStudentDetail:
    return AdminStudentDetail(
        student_id=student_id,
        full_name="Student One",
        parent_id=parent_id,
        status="active",
        enrolled_sessions=[
            AdminStudentSessionSummary(
                enrollment_id=enrollment_id,
                session_id=f"session-{enrollment_id}",
                session_title="Junior A",
                status="active",
            )
            for enrollment_id in (enrollment_ids or [])
        ],
    )


def _override_admin_student(admin_client, student: AdminStudentDetail | None) -> None:
    admin_client.use_cases.get_admin_student = _FakeGetAdminStudent(student)


def _override_ledger(admin_client, ledger: _FakeLedger) -> None:
    async def send_billing_invoice(invoice_id: str) -> dict:
        result = await SendInvoice(
            ledger=ledger,
            stripe=getattr(admin_client, "_test_invoice_stripe", None),
            email=getattr(admin_client, "_test_invoice_email", None),
            success_url="https://app.example.com/parent/payments?invoice=paid",
            cancel_url="https://app.example.com/parent/payments?invoice=cancelled",
        ).execute(invoice_id)
        return {
            "invoice_id": result.invoice.invoice_id,
            "delivery_status": result.invoice.delivery_status,
            "sent_at": result.invoice.sent_at,
            "last_sent_at": result.invoice.last_sent_at,
            "checkout_url": result.checkout_url,
        }

    async def add_invoice_line(**kwargs) -> dict:
        result = await AddInvoiceLine(ledger=ledger).execute(AddInvoiceLineCommand(**kwargs))
        return {
            "line": result.line.model_dump(mode="python"),
            "invoice": result.invoice.model_dump(mode="python"),
        }

    async def remove_invoice_line(*, invoice_id: str, line_id: str) -> None:
        await RemoveInvoiceLine(ledger=ledger).execute(
            RemoveInvoiceLineCommand(invoice_id=invoice_id, line_id=line_id)
        )

    async def void_billing_invoice(*, invoice_id: str, reason: str) -> None:
        invoice = await ledger.get_invoice(invoice_id)
        if invoice is None:
            raise ValueError("invoice not found")
        if (
            invoice.status in {"partially_paid", "paid"}
            or invoice.balance_due_cents != invoice.total_cents
        ):
            raise ValueError(
                "cannot void invoice with recorded payments; issue refund or credit first"
            )
        voided = ledger_domain.void_invoice(invoice, reason=reason, now=datetime.now(UTC))
        await ledger.save_invoice(voided)

    async def create_student_invoice(
        *,
        student_id: str,
        parent_id: str,
        period: str,
        due_date: date,
        enrollment_id: str | None,
    ) -> dict:
        invoice = LedgerInvoice(
            invoice_id="inv-test",
            academy_id="acad",
            parent_id=parent_id,
            student_id=student_id,
            enrollment_id=enrollment_id,
            period=period,
            status="draft",
            subtotal_cents=0,
            discount_cents=0,
            total_cents=0,
            balance_due_cents=0,
            currency="usd",
            due_date=due_date,
            created_at=NOW,
            updated_at=NOW,
        )
        created = await ledger.create_invoice(
            invoice,
            lines=[],
            idempotency_key=f"admin-invoice-{invoice.invoice_id}",
        )
        return created.model_dump(mode="json")

    admin_client.use_cases.send_billing_invoice = send_billing_invoice
    admin_client.use_cases.add_invoice_line = add_invoice_line
    admin_client.use_cases.remove_invoice_line = remove_invoice_line
    admin_client.use_cases.void_billing_invoice = void_billing_invoice
    admin_client.use_cases.create_student_invoice = create_student_invoice


def _override_invoice_stripe(admin_client, stripe: _FakeInvoiceStripe) -> None:
    admin_client._test_invoice_stripe = stripe


def _override_invoice_email(admin_client, email: _FakeInvoiceEmail) -> None:
    admin_client._test_invoice_email = email


def test_list_payments_returns_recent(admin_client):
    _seed_payment(admin_client.seed, "pay-1", 15000)
    _seed_payment(admin_client.seed, "pay-2", 22500)
    r = admin_client.get("/api/v2/admin/payments")
    assert r.status_code == 200, r.text
    body = r.json()
    ids = {p["payment_id"] for p in body["payments"]}
    assert ids == {"pay-1", "pay-2"}


def test_list_payments_exposes_invoice_id_for_invoice_actions(admin_client):
    async def list_payments_recent():
        return [
            {
                "payment_id": "inv-display-row",
                "invoice_id": "inv-internal-1",
                "parent_id": "parent-1",
                "student_id": "student-1",
                "student_name": "Student One",
                "session_id": "session-1",
                "period": "2026-06",
                "amount_cents": 6000,
                "discount_cents": 0,
                "final_amount_cents": 6000,
                "amount_received_cents": 0,
                "paid_amount_cents": 0,
                "balance_due_cents": 6000,
                "overpayment_credit_cents": 0,
                "currency": "usd",
                "status": "pending",
                "refunded_cents": 0,
                "invoice_number": "INV-202606-DISPLAY",
                "payment_method": "invoice",
                "stripe_linked": False,
                "created_at": NOW,
            }
        ]

    admin_client.use_cases.list_payments_recent = list_payments_recent
    r = admin_client.get("/api/v2/admin/payments")
    assert r.status_code == 200, r.text
    payment = r.json()["payments"][0]
    assert payment["invoice_id"] == "inv-internal-1"
    assert payment["invoice_number"] == "INV-202606-DISPLAY"


def test_list_payments_wrong_persona_404(coach_on_admin_client):
    r = coach_on_admin_client.get("/api/v2/admin/payments")
    assert r.status_code == 404


def test_issue_refund_happy_path(admin_client):
    _seed_payment(admin_client.seed, "pay-1", 15000)
    r = admin_client.post(
        "/api/v2/admin/payments/refund",
        json={"payment_id": "pay-1", "amount_cents": 5000, "reason": "admin_initiated"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["refunded_cents"] == 5000
    assert body["total_refunded_cents"] == 5000
    # Stripe gateway recorded the refund.
    refunds = admin_client.seed["stripe"].refunds
    assert len(refunds) == 1
    assert refunds[0]["amount_cents"] == 5000


def test_issue_refund_exceeds_amount_returns_400(admin_client):
    _seed_payment(admin_client.seed, "pay-1", 15000)
    r = admin_client.post(
        "/api/v2/admin/payments/refund",
        json={"payment_id": "pay-1", "amount_cents": 99999},
    )
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "Billing.RefundExceedsAmount"


def test_issue_refund_wrong_persona_404(parent_on_admin_client):
    r = parent_on_admin_client.post(
        "/api/v2/admin/payments/refund",
        json={"payment_id": "pay-x", "amount_cents": 1},
    )
    assert r.status_code == 404


def test_generate_monthly_payments(admin_client):
    r = admin_client.post(
        "/api/v2/admin/payments/generate-monthly",
        json={"period": "2026-05"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 1
    assert body["repaired_orphan_keys"] == 0
    assert body["repaired_partial_invoices"] == 0
    assert body["failed_repair"] == 0
    assert body["skipped_details"] == []
    assert admin_client.seed["payments"].generated_periods == ["2026-05"]


def test_generate_monthly_payments_returns_skipped_details(admin_client):
    admin_client.seed["payments"].monthly_result = {
        "created": 0,
        "skipped_existing": 0,
        "skipped_no_charge": 0,
        "skipped_autopay": 0,
        "skipped_paused": 1,
        "skipped_details": [
            {
                "enrollment_id": "enroll-1",
                "student_id": "student-1",
                "student_name": "A Student",
                "reason_code": "fixed_pause",
                "source": "pause_request",
                "billing_period": "2026-06",
                "resume_on": "2026-07-15",
                "review_on": None,
                "expires_on": None,
                "needs_review": False,
                "metadata": {"pause_request_id": "pause-1"},
            }
        ],
    }

    r = admin_client.post(
        "/api/v2/admin/payments/generate-monthly",
        json={"period": "2026-06"},
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["skipped_paused"] == 1
    assert body["skipped_details"][0]["enrollment_id"] == "enroll-1"
    assert body["skipped_details"][0]["reason_code"] == "fixed_pause"


def test_mark_payment_paid(admin_client):
    _seed_payment(admin_client.seed, "pay-manual", status="pending", stripe=False)
    r = admin_client.post(
        "/api/v2/admin/payments/pay-manual/mark-paid",
        json={"payment_method": "cash", "notes": "desk", "payment_date": "2026-06-11"},
    )
    assert r.status_code == 200, r.text
    assert admin_client.seed["payments"].rows["pay-manual"].status == "succeeded"
    record = admin_client.seed["payments"].manual_records["pay-manual"]
    # Audit trail: the authenticated admin and the entered payment date are persisted.
    assert record["recorded_by"] == "u-admin"
    assert str(record["payment_date"]) == "2026-06-11"


def test_apply_payment_discount(admin_client):
    _seed_payment(admin_client.seed, "pay-pending", status="pending", stripe=False)
    r = admin_client.post(
        "/api/v2/admin/payments/pay-pending/discount",
        json={"discount_cents": 2500, "reason": "sibling discount"},
    )
    assert r.status_code == 200, r.text
    assert admin_client.seed["payments"].discounts["pay-pending"] == 2500


def test_undo_manual_paid_blocks_stripe_linked(admin_client):
    _seed_payment(admin_client.seed, "pay-stripe", status="succeeded", stripe=True)
    r = admin_client.post("/api/v2/admin/payments/pay-stripe/undo-paid")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "Billing.PaymentOperationNotAllowed"


def test_undo_manual_paid(admin_client):
    _seed_payment(admin_client.seed, "pay-cash", status="succeeded", stripe=False)
    r = admin_client.post("/api/v2/admin/payments/pay-cash/undo-paid")
    assert r.status_code == 200, r.text
    assert admin_client.seed["payments"].rows["pay-cash"].status == "pending"


# --- # FINANCE ---


def test_list_payouts_returns_seeded(admin_client):
    admin_client.seed["payouts"].rows["po-1"] = Payout(
        payout_id="po-1",
        academy_id="acad",
        coach_id="coach-1",
        amount_cents=80000,
        period_start=datetime(2026, 4, 1, tzinfo=UTC),
        period_end=datetime(2026, 4, 30, tzinfo=UTC),
    )
    r = admin_client.get("/api/v2/admin/finance/payouts")
    assert r.status_code == 200
    assert r.json()["payouts"][0]["payout_id"] == "po-1"


def test_list_payouts_wrong_persona_404(coach_on_admin_client):
    r = coach_on_admin_client.get("/api/v2/admin/finance/payouts")
    assert r.status_code == 404


def test_record_expense_creates_entry(admin_client):
    r = admin_client.post(
        "/api/v2/admin/finance/expenses",
        json={"category": "rent", "amount_cents": 250000, "note": "May rent"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["category"] == "rent"
    assert body["amount_cents"] == 250000
    assert body["note"] == "May rent"


def test_record_expense_wrong_persona_404(parent_on_admin_client):
    r = parent_on_admin_client.post(
        "/api/v2/admin/finance/expenses",
        json={"category": "rent", "amount_cents": 1},
    )
    assert r.status_code == 404


def test_revenue_aggregates_by_month(admin_client):
    _seed_payment(admin_client.seed, "pay-1", 15000, status="succeeded")

    r = admin_client.get("/api/v2/admin/finance/revenue")

    assert r.status_code == 200
    [month_total] = r.json()["by_month"].values()
    assert month_total == 15000


def test_revenue_skips_waived_payments(admin_client):
    _seed_payment(admin_client.seed, "pay-1", 15000, status="succeeded")
    _seed_payment(admin_client.seed, "pay-waived", 22500, status="waived")

    r = admin_client.get("/api/v2/admin/finance/revenue")

    assert r.status_code == 200, r.text
    [month_total] = r.json()["by_month"].values()
    assert month_total == 15000


def test_revenue_wrong_persona_404(coach_on_admin_client):
    r = coach_on_admin_client.get("/api/v2/admin/finance/revenue")
    assert r.status_code == 404


def test_send_invoice_returns_checkout_url_when_stripe_configured(admin_client):
    ledger = _FakeLedger(invoices=[_invoice(status="open", balance_due_cents=7_000)])
    stripe = _FakeInvoiceStripe()
    _override_ledger(admin_client, ledger)
    _override_invoice_stripe(admin_client, stripe)

    response = admin_client.post("/api/v2/admin/billing/invoices/inv-1/send")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["checkout_url"] == "https://checkout.stripe.test/invoice"
    assert body["delivery_status"] == "not_sent"
    assert stripe.calls == [
        {
            "invoice_id": "inv-1",
            "amount_cents": 7_000,
            "currency": "usd",
            "success_url": "https://app.example.com/parent/payments?invoice=paid",
            "cancel_url": "https://app.example.com/parent/payments?invoice=cancelled",
            "metadata": {
                "invoice_id": "inv-1",
                "source": "invoice_pay_link",
                "academy_id": "acad",
                "parent_id": "parent-1",
            },
            "idempotency_key": "invoice-checkout:inv-1:7000",
        }
    ]


def test_billing_reconciliation_report_is_read_only(admin_client):
    async def report(**kwargs):
        assert kwargs == {
            "stripe_invoice_id": "in_123",
            "payment_intent_id": "pi_123",
        }
        return {
            "result": "AMOUNT_MISMATCH",
            "stripe_invoice_id": "in_123",
            "payment_intent_id": "pi_123",
            "stripe_customer_id": "cus_123",
            "local_invoice_id": "inv-123",
            "ledger_payment_id": None,
            "payment_allocation_id": None,
            "mismatches": [
                {
                    "code": "AMOUNT_MISMATCH",
                    "message": "Stripe amount_paid differs from ledger invoice total",
                    "stripe_value": 7000,
                    "local_value": 6000,
                }
            ],
            "checked_at": NOW,
        }

    admin_client.use_cases.get_billing_reconciliation_report = report

    response = admin_client.get(
        "/api/v2/admin/billing/reconciliation?stripe_invoice_id=in_123&payment_intent_id=pi_123"
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["result"] == "AMOUNT_MISMATCH"
    assert body["stripe_invoice_id"] == "in_123"
    assert body["payment_intent_id"] == "pi_123"
    assert body["local_invoice_id"] == "inv-123"
    assert body["mismatches"][0]["code"] == "AMOUNT_MISMATCH"
    assert body["mismatches"][0]["stripe_value"] == 7000
    assert body["mismatches"][0]["local_value"] == 6000


def test_billing_webhook_queue_returns_failed_and_quarantined_events(admin_client):
    async def queue(*, status, limit):
        assert status == "quarantined"
        assert limit == 25
        return [
            {
                "event_id": "evt_quarantine_1",
                "event_type": "invoice.paid",
                "status": "quarantined",
                "object_id": "in_duplicate",
                "object_type": "invoice",
                "received_at": NOW,
                "last_attempt_at": NOW,
                "retry_count": 2,
                "error_message": "duplicate obligation",
            }
        ]

    admin_client.use_cases.list_billing_webhook_events = queue

    response = admin_client.get("/api/v2/admin/billing/webhooks?status=quarantined&limit=25")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["events"] == [
        {
            "event_id": "evt_quarantine_1",
            "event_type": "invoice.paid",
            "status": "quarantined",
            "object_id": "in_duplicate",
            "object_type": "invoice",
            "received_at": NOW.isoformat().replace("+00:00", "Z"),
            "last_attempt_at": NOW.isoformat().replace("+00:00", "Z"),
            "retry_count": 2,
            "error_message": "duplicate obligation",
        }
    ]


def test_send_invoice_with_email_marks_sent_and_passes_checkout_url(admin_client):
    ledger = _FakeLedger(invoices=[_invoice(status="open", balance_due_cents=7_000)])
    stripe = _FakeInvoiceStripe()
    email = _FakeInvoiceEmail()
    _override_ledger(admin_client, ledger)
    _override_invoice_stripe(admin_client, stripe)
    _override_invoice_email(admin_client, email)

    response = admin_client.post("/api/v2/admin/billing/invoices/inv-1/send")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["checkout_url"] == "https://checkout.stripe.test/invoice"
    assert body["delivery_status"] == "sent"
    assert email.calls == [
        {
            "parent_id": "parent-1",
            "invoice_id": "inv-1",
            "period": "2026-06",
            "total_cents": 7_000,
            "balance_due_cents": 7_000,
            "currency": "usd",
            "checkout_url": "https://checkout.stripe.test/invoice",
        }
    ]


async def test_invoice_email_adapter_requires_parent_membership_in_request_academy() -> None:
    sender = _FakeEmailSender()
    memberships = _FakeMembershipRepo(
        AcademyMembership(
            membership_id="mem-1",
            academy_id="other-acad",
            user_id="parent-1",
            roles=("parent",),
            status="active",
        )
    )
    users = _FakeUserRepo(
        User(user_id="parent-1", email="parent@example.com", display_name="Parent One")
    )
    adapter = _InvoiceEmailAdapter(
        memberships=memberships,
        users=users,
        sender=sender,
    )

    with tenant_scope("acad"), pytest.raises(ValueError, match="active membership"):
        await adapter.send_invoice_email(
            parent_id="parent-1",
            invoice_id="inv-1",
            period="2026-06",
            total_cents=7_000,
            balance_due_cents=7_000,
            currency="usd",
            checkout_url="https://checkout.stripe.test/invoice",
        )

    assert sender.calls == []
    assert users.calls == []


async def test_invoice_email_adapter_sends_after_membership_match() -> None:
    sender = _FakeEmailSender()
    memberships = _FakeMembershipRepo(
        AcademyMembership(
            membership_id="mem-1",
            academy_id="acad",
            user_id="parent-1",
            roles=("parent",),
            status="active",
        )
    )
    users = _FakeUserRepo(
        User(user_id="parent-1", email="parent@example.com", display_name="Parent One")
    )
    adapter = _InvoiceEmailAdapter(
        memberships=memberships,
        users=users,
        sender=sender,
    )

    with tenant_scope("acad"):
        await adapter.send_invoice_email(
            parent_id="parent-1",
            invoice_id="inv-1",
            period="2026-06",
            total_cents=7_000,
            balance_due_cents=7_000,
            currency="usd",
            checkout_url="https://checkout.stripe.test/invoice",
        )

    assert sender.calls[0]["recipient"].email == "parent@example.com"
    assert sender.calls[0]["recipient"].user_id == "parent-1"
    assert "https://checkout.stripe.test/invoice" in sender.calls[0]["body"]


def test_add_invoice_line_returns_refreshed_invoice_totals(admin_client):
    ledger = _FakeLedger(
        invoices=[
            _invoice(
                status="open", subtotal_cents=2_000, total_cents=2_000, balance_due_cents=2_000
            )
        ],
        lines=[
            _invoice_line(line_id="line-existing", amount_cents=2_000),
        ],
    )
    _override_ledger(admin_client, ledger)

    response = admin_client.post(
        "/api/v2/admin/billing/invoices/inv-1/lines",
        json={
            "description": "Racket",
            "line_type": "equipment",
            "quantity": 1,
            "unit_amount_cents": 4_000,
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["amount_cents"] == 4_000
    assert body["invoice_total_cents"] == 6_000
    assert body["invoice_balance_due_cents"] == 6_000
    assert body["invoice_status"] == "open"


def test_add_invoice_line_rejects_negative_unit_amount(admin_client):
    ledger = _FakeLedger(invoices=[_invoice(status="draft")])
    _override_ledger(admin_client, ledger)

    response = admin_client.post(
        "/api/v2/admin/billing/invoices/inv-1/lines",
        json={
            "description": "Bad adjustment",
            "line_type": "fee",
            "quantity": 1,
            "unit_amount_cents": -1,
        },
    )

    assert response.status_code == 422


def test_add_invoice_adjustment_allows_negative_discount_line(admin_client):
    ledger = _FakeLedger(
        invoices=[
            _invoice(
                status="open", subtotal_cents=7_000, total_cents=7_000, balance_due_cents=7_000
            )
        ],
        lines=[_invoice_line(line_id="line-tuition", amount_cents=7_000)],
    )
    _override_ledger(admin_client, ledger)

    response = admin_client.post(
        "/api/v2/admin/billing/invoices/inv-1/adjustments",
        json={
            "description": "Sibling discount",
            "amount_cents": -1_000,
            "reason": "Manual sibling discount",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["amount_cents"] == -1_000
    assert body["line_type"] == "adjustment"
    assert body["invoice_total_cents"] == 6_000
    assert body["invoice_balance_due_cents"] == 6_000
    assert body["invoice_status"] == "open"


def test_record_invoice_manual_payment_route(admin_client):
    async def record_manual_payment(**kwargs):
        assert kwargs == {
            "invoice_id": "inv-1",
            "amount_cents": 2_500,
            "payment_method": "check",
            "reference_number": "1001",
            "notes": "Front desk payment",
        }
        return {
            "invoice_id": "inv-1",
            "payment_id": "manual-1",
            "invoice_status": "partially_paid",
            "balance_due_cents": 4_500,
        }

    admin_client.use_cases.record_manual_payment = record_manual_payment

    response = admin_client.post(
        "/api/v2/admin/billing/invoices/inv-1/record-payment",
        json={
            "amount_cents": 2_500,
            "payment_method": "check",
            "reference_number": "1001",
            "notes": "Front desk payment",
        },
    )

    assert response.status_code == 201, response.text
    assert response.json() == {
        "invoice_id": "inv-1",
        "payment_id": "manual-1",
        "invoice_status": "partially_paid",
        "balance_due_cents": 4_500,
    }


def test_refund_invoice_route_uses_invoice_native_use_case(admin_client):
    async def issue_invoice_refund(**kwargs):
        assert kwargs == {
            "invoice_id": "inv-1",
            "amount_cents": 3_000,
            "reason": "duplicate",
        }
        return {
            "invoice_id": "inv-1",
            "payment_id": "lp-1",
            "stripe_refund_id": "re_123",
            "refunded_cents": 3_000,
            "total_refunded_cents": 3_000,
        }

    admin_client.use_cases.issue_invoice_refund = issue_invoice_refund

    response = admin_client.post(
        "/api/v2/admin/billing/invoices/inv-1/refund",
        json={"amount_cents": 3_000, "reason": "duplicate"},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "invoice_id": "inv-1",
        "payment_id": "lp-1",
        "stripe_refund_id": "re_123",
        "refunded_cents": 3_000,
        "total_refunded_cents": 3_000,
    }


def test_remove_invoice_line_allows_draft_and_recomputes_totals(admin_client):
    ledger = _FakeLedger(
        invoices=[_invoice(status="draft")],
        lines=[
            _invoice_line(line_id="line-keep", amount_cents=3_000),
            _invoice_line(line_id="line-remove", amount_cents=4_000),
        ],
    )
    _override_ledger(admin_client, ledger)

    response = admin_client.delete("/api/v2/admin/billing/invoices/inv-1/lines/line-remove")

    assert response.status_code == 204, response.text
    assert "line-remove" not in ledger.lines
    updated = ledger.invoices["inv-1"]
    assert updated.status == "draft"
    assert updated.total_cents == 3_000
    assert updated.balance_due_cents == 3_000


def test_remove_invoice_line_rejects_non_draft(admin_client):
    ledger = _FakeLedger(
        invoices=[_invoice(status="open")],
        lines=[_invoice_line(line_id="line-1", amount_cents=7_000)],
    )
    _override_ledger(admin_client, ledger)

    response = admin_client.delete("/api/v2/admin/billing/invoices/inv-1/lines/line-1")

    assert response.status_code == 409
    assert "draft invoice" in response.json()["detail"]
    assert "line-1" in ledger.lines


def test_remove_invoice_line_missing_line_returns_404(admin_client):
    ledger = _FakeLedger(invoices=[_invoice(status="draft")])
    _override_ledger(admin_client, ledger)

    response = admin_client.delete("/api/v2/admin/billing/invoices/inv-1/lines/missing-line")

    assert response.status_code == 404
    assert "missing-line" in response.json()["detail"]


def test_void_invoice_requires_reason_body(admin_client):
    ledger = _FakeLedger(invoices=[_invoice(status="open")])
    _override_ledger(admin_client, ledger)

    response = admin_client.post("/api/v2/admin/billing/invoices/inv-1/void")

    assert response.status_code == 422


def test_void_invoice_rejects_recorded_payment_activity(admin_client):
    ledger = _FakeLedger(
        invoices=[
            _invoice(
                status="partially_paid",
                subtotal_cents=7_000,
                total_cents=7_000,
                balance_due_cents=3_000,
            )
        ]
    )
    _override_ledger(admin_client, ledger)

    response = admin_client.post(
        "/api/v2/admin/billing/invoices/inv-1/void",
        json={"reason": "Cannot collect"},
    )

    assert response.status_code == 409
    assert "recorded payments" in response.json()["detail"]
    assert ledger.invoices["inv-1"].status == "partially_paid"


def test_void_invoice_uses_request_body_reason(admin_client, monkeypatch):
    ledger = _FakeLedger(invoices=[_invoice(status="open")])
    _override_ledger(admin_client, ledger)
    captured: dict[str, str] = {}

    def _void_invoice(invoice, *, reason: str, now: datetime):
        captured["reason"] = reason
        return invoice.model_copy(update={"status": "void", "updated_at": now})

    monkeypatch.setattr(ledger_domain, "void_invoice", _void_invoice)

    response = admin_client.post(
        "/api/v2/admin/billing/invoices/inv-1/void",
        json={"reason": " billing correction "},
    )

    assert response.status_code == 200, response.text
    assert captured["reason"] == "billing correction"
    assert ledger.invoices["inv-1"].status == "void"


def test_create_student_invoice_rejects_body_student_mismatch(admin_client):
    ledger = _FakeLedger()
    _override_ledger(admin_client, ledger)
    _override_admin_student(admin_client, _student_detail())

    response = admin_client.post(
        "/api/v2/admin/students/student-1/invoices",
        json={
            "student_id": "student-2",
            "parent_id": "parent-1",
            "period": "2026-06",
            "due_date": "2026-06-30",
        },
    )

    assert response.status_code == 409
    assert ledger.invoices == {}


def test_create_student_invoice_rejects_wrong_parent(admin_client):
    ledger = _FakeLedger()
    _override_ledger(admin_client, ledger)
    _override_admin_student(admin_client, _student_detail())

    response = admin_client.post(
        "/api/v2/admin/students/student-1/invoices",
        json={
            "student_id": "student-1",
            "parent_id": "parent-2",
            "period": "2026-06",
            "due_date": "2026-06-30",
        },
    )

    assert response.status_code == 409
    assert "parent" in response.json()["detail"]
    assert ledger.invoices == {}


def test_create_student_invoice_rejects_wrong_enrollment(admin_client):
    ledger = _FakeLedger()
    _override_ledger(admin_client, ledger)
    _override_admin_student(admin_client, _student_detail(enrollment_ids=["enroll-2"]))

    response = admin_client.post(
        "/api/v2/admin/students/student-1/invoices",
        json={
            "student_id": "student-1",
            "parent_id": "parent-1",
            "period": "2026-06",
            "due_date": "2026-06-30",
            "enrollment_id": "enroll-1",
        },
    )

    assert response.status_code == 409
    assert "enrollment" in response.json()["detail"]
    assert ledger.invoices == {}


def test_create_student_invoice_allows_matching_student_parent_and_enrollment(admin_client):
    ledger = _FakeLedger()
    _override_ledger(admin_client, ledger)
    _override_admin_student(admin_client, _student_detail(enrollment_ids=["enroll-1"]))

    response = admin_client.post(
        "/api/v2/admin/students/student-1/invoices",
        json={
            "student_id": "student-1",
            "parent_id": "parent-1",
            "period": "2026-06",
            "due_date": "2026-06-30",
            "enrollment_id": "enroll-1",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["student_id"] == "student-1"
    assert body["parent_id"] == "parent-1"
    assert body["enrollment_id"] == "enroll-1"
    assert body["status"] == "draft"
    assert len(ledger.invoices) == 1


# --------------------------------------------------------------------------- #
# Billing Health (#235)
# --------------------------------------------------------------------------- #
def test_list_reconciliation_runs(admin_client):
    runs = [
        {
            "run_id": "r-new",
            "academy_id": "acad",
            "started_at": datetime(2026, 6, 21, 10, 2, tzinfo=UTC),
            "finished_at": datetime(2026, 6, 21, 10, 2, 1, tzinfo=UTC),
            "scanned": 8,
            "repaired": 0,
            "skipped": 8,
            "quarantined": 0,
            "failed": 0,
            "errors": [],
        }
    ]

    async def list_reconciliation_runs():
        return runs

    admin_client.use_cases.list_reconciliation_runs = list_reconciliation_runs
    r = admin_client.get("/api/v2/admin/billing/reconciliation-runs")
    assert r.status_code == 200, r.text
    body = r.json()
    assert [x["run_id"] for x in body["runs"]] == ["r-new"]
    assert body["runs"][0]["scanned"] == 8


def test_run_reconciliation_now(admin_client):
    async def run_reconciliation():
        return {
            "run_id": "r1",
            "scanned": 3,
            "repaired": 1,
            "skipped": 2,
            "quarantined": 0,
            "failed": 0,
            "errors": [],
        }

    admin_client.use_cases.run_reconciliation = run_reconciliation
    r = admin_client.post("/api/v2/admin/billing/reconcile-now")
    assert r.status_code == 200, r.text
    assert r.json()["repaired"] == 1


def test_run_reconciliation_unconfigured_returns_503(admin_client):
    async def run_reconciliation():
        raise RuntimeError("Stripe reconciliation not configured")

    admin_client.use_cases.run_reconciliation = run_reconciliation
    r = admin_client.post("/api/v2/admin/billing/reconcile-now")
    assert r.status_code == 503


def test_list_failed_payment_attempts(admin_client):
    rows = [
        {
            "invoice_id": "inv-1",
            "parent_id": "p1",
            "parent_name": "Sarah M.",
            "period": "2026-06",
            "total_cents": 12000,
            "balance_due_cents": 12000,
            "currency": "usd",
            "latest_attempt_at": datetime(2026, 6, 21, 9, 45, tzinfo=UTC),
            "latest_decline_code": "card_declined",
            "attempt_count": 2,
        }
    ]

    async def list_failed_payment_attempts():
        return rows

    admin_client.use_cases.list_failed_payment_attempts = list_failed_payment_attempts
    r = admin_client.get("/api/v2/admin/billing/failed-payment-attempts")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rows"][0]["latest_decline_code"] == "card_declined"
    assert body["rows"][0]["attempt_count"] == 2


def test_list_invoice_attempts(admin_client):
    attempts = [
        {
            "attempt_id": "a2",
            "status": "failed",
            "amount_cents": 12000,
            "currency": "usd",
            "stripe_payment_intent_id": "pi_2",
            "failure_code": "card_declined",
            "failure_message": "Your card was declined.",
            "created_at": datetime(2026, 6, 21, 9, 45, tzinfo=UTC),
        }
    ]

    async def list_invoice_attempts(invoice_id):
        assert invoice_id == "inv-1"
        return attempts

    admin_client.use_cases.list_invoice_attempts = list_invoice_attempts
    r = admin_client.get("/api/v2/admin/billing/invoices/inv-1/attempts")
    assert r.status_code == 200, r.text
    assert r.json()["attempts"][0]["status"] == "failed"


def test_list_invoice_attempts_not_found_returns_404(admin_client):
    async def list_invoice_attempts(invoice_id):
        raise ValueError("invoice not found")

    admin_client.use_cases.list_invoice_attempts = list_invoice_attempts
    r = admin_client.get("/api/v2/admin/billing/invoices/missing/attempts")
    assert r.status_code == 404


def test_replay_webhook_event(admin_client):
    async def replay_webhook_event(event_id):
        assert event_id == "evt_1"
        return True

    admin_client.use_cases.replay_webhook_event = replay_webhook_event
    r = admin_client.post("/api/v2/admin/billing/webhook-events/evt_1/replay")
    assert r.status_code == 200, r.text
    assert r.json() == {"replayed": True, "event_id": "evt_1"}


def test_replay_webhook_event_not_found_returns_404(admin_client):
    async def replay_webhook_event(event_id):
        raise ValueError("quarantined event not found")

    admin_client.use_cases.replay_webhook_event = replay_webhook_event
    r = admin_client.post("/api/v2/admin/billing/webhook-events/missing/replay")
    assert r.status_code == 404
