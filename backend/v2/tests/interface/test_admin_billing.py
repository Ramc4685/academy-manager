"""Admin billing + finance BFF — happy + wrong-persona 404."""

from __future__ import annotations

from datetime import UTC, date, datetime

from backend.v2.contexts.billing.application.use_cases.finance import Payout
from backend.v2.contexts.billing.domain import ledger as ledger_domain
from backend.v2.contexts.billing.domain.ledger import InvoiceLine, LedgerInvoice
from backend.v2.contexts.billing.domain.models import Payment
from backend.v2.contexts.enrollment.application.use_cases.admin_directory import (
    AdminStudentDetail,
    AdminStudentSessionSummary,
)
from backend.v2.interfaces.admin import billing_routes as admin_billing_routes


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
    admin_client.app.dependency_overrides[admin_billing_routes._get_ledger_repo] = lambda: ledger


def test_list_payments_returns_recent(admin_client):
    _seed_payment(admin_client.seed, "pay-1", 15000)
    _seed_payment(admin_client.seed, "pay-2", 22500)
    r = admin_client.get("/api/v2/admin/payments")
    assert r.status_code == 200, r.text
    body = r.json()
    ids = {p["payment_id"] for p in body["payments"]}
    assert ids == {"pay-1", "pay-2"}


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
    assert admin_client.seed["payments"].generated_periods == ["2026-05"]


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
    # Revenue query in AcademyRevenueQuery only runs with a parent_id filter
    # in the Wave 3 stub; admin route passes None which yields {}.
    r = admin_client.get("/api/v2/admin/finance/revenue")
    assert r.status_code == 200
    assert r.json() == {"by_month": {}}


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
