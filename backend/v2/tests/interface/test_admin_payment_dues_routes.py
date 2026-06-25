"""Admin payment, invoice, and dues route contracts."""

from __future__ import annotations

from datetime import UTC, datetime

from backend.v2.contexts.billing.domain.models import Payment


def _seed_pending_payment(admin_client, payment_id: str = "pay-manual") -> None:
    admin_client.seed["payments"].rows[payment_id] = Payment(
        payment_id=payment_id,
        academy_id="acad",
        parent_id="parent-1",
        student_id="student-1",
        session_id="session-1",
        amount_cents=10_000,
        currency="usd",
        status="pending",
        refunded_cents=0,
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
        updated_at=datetime(2026, 5, 1, tzinfo=UTC),
    )


def test_manual_partial_payment_keeps_invoice_open(admin_client) -> None:
    _seed_pending_payment(admin_client)

    response = admin_client.post(
        "/api/v2/admin/payments/pay-manual/mark-paid",
        json={
            "payment_method": "venmo",
            "amount_received_cents": 4_000,
            "reference_number": "VENMO-1",
            "notes": "Partial payment",
        },
    )

    assert response.status_code == 200, response.text
    payment = admin_client.seed["payments"].rows["pay-manual"]
    assert payment.status == "partially_paid"
    assert (
        admin_client.seed["payments"].manual_records["pay-manual"]["amount_received_cents"] == 4_000
    )
    assert admin_client.seed["payments"].manual_records["pay-manual"]["balance_due_cents"] == 6_000


def test_manual_exact_payment_closes_invoice(admin_client) -> None:
    _seed_pending_payment(admin_client)

    response = admin_client.post(
        "/api/v2/admin/payments/pay-manual/mark-paid",
        json={"payment_method": "cash", "amount_received_cents": 10_000},
    )

    assert response.status_code == 200, response.text
    assert admin_client.seed["payments"].rows["pay-manual"].status == "succeeded"
    assert admin_client.seed["payments"].manual_records["pay-manual"]["balance_due_cents"] == 0


def test_manual_overpayment_creates_credit(admin_client) -> None:
    _seed_pending_payment(admin_client)

    response = admin_client.post(
        "/api/v2/admin/payments/pay-manual/mark-paid",
        json={"payment_method": "check", "amount_received_cents": 12_500},
    )

    assert response.status_code == 200, response.text
    assert admin_client.seed["payments"].rows["pay-manual"].status == "succeeded"
    assert admin_client.seed["payments"].credits == [
        {"payment_id": "pay-manual", "parent_id": "parent-1", "amount_cents": 2_500}
    ]


def test_discount_route_requires_reason(admin_client) -> None:
    _seed_pending_payment(admin_client, "pay-discount")

    missing_reason = admin_client.post(
        "/api/v2/admin/payments/pay-discount/discount",
        json={"discount_cents": 1_500},
    )
    assert missing_reason.status_code == 422

    ok = admin_client.post(
        "/api/v2/admin/payments/pay-discount/discount",
        json={"discount_cents": 1_500, "reason": "Sibling discount"},
    )
    assert ok.status_code == 200, ok.text
    assert admin_client.seed["payments"].discount_reasons["pay-discount"] == "Sibling discount"


def test_invoice_detail_shows_lines_allocations_and_credit_usage(admin_client) -> None:
    admin_client.seed["invoice_details"]["inv-1"] = {
        "invoice_id": "inv-1",
        "invoice_number": "inv-1",
        "period": "2026-05",
        "lines": [
            {
                "line_id": "line-1",
                "invoice_id": "inv-1",
                "line_type": "tuition",
                "description": "May tuition",
                "quantity": 1,
                "unit_amount_cents": 10_000,
                "amount_cents": 10_000,
            }
        ],
        "subtotal_cents": 10_000,
        "discount_cents": 0,
        "total_cents": 10_000,
        "balance_due_cents": 6_000,
        "due_amount_cents": 6_000,
        "paid_amount_cents": 4_000,
        "status": "partially_paid",
        "allocations": [{"payment_id": "pay-1", "amount_cents": 4_000}],
        "credit_usage": [{"credit_id": "credit-1", "amount_cents": 1_000}],
        "invoice_pdf_artifact_id": None,
        "receipt_artifact_id": None,
    }

    response = admin_client.get("/api/v2/admin/billing/invoices/inv-1")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["invoice_id"] == "inv-1"
    assert body["lines"] == [
        {
            "line_id": "line-1",
            "invoice_id": "inv-1",
            "line_type": "tuition",
            "description": "May tuition",
            "quantity": 1,
            "unit_amount_cents": 10000,
            "amount_cents": 10000,
        }
    ]
    assert body["subtotal_cents"] == 10000
    assert body["discount_cents"] == 0
    assert body["total_cents"] == 10000
    assert body["balance_due_cents"] == 6000
    assert body["due_amount_cents"] == 6000
    assert body["paid_amount_cents"] == 4000
    assert body["status"] == "partially_paid"
    assert body["allocations"] == [{"payment_id": "pay-1", "amount_cents": 4000}]
    assert body["credit_usage"] == [{"credit_id": "credit-1", "amount_cents": 1000}]


def test_invoice_artifact_generation_is_request_based(admin_client) -> None:
    admin_client.seed["invoice_details"]["inv-1"] = {
        "invoice_number": "inv-1",
        "period": "2026-05",
        "lines": [{"description": "May tuition", "amount_cents": 10_000}],
        "due_amount_cents": 0,
        "paid_amount_cents": 10_000,
        "status": "paid",
        "allocations": [{"payment_id": "pay-1", "amount_cents": 10_000}],
        "credit_usage": [],
        "invoice_pdf_artifact_id": None,
        "receipt_artifact_id": None,
    }

    response = admin_client.post(
        "/api/v2/admin/billing/invoices/inv-1/artifacts",
        json={"artifact_type": "receipt"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["artifact_type"] == "receipt"
    assert body["status"] == "generated"
    assert body["artifact_id"]


def test_dues_reminders_support_selected_recipients(admin_client) -> None:
    response = admin_client.post(
        "/api/v2/admin/dues-reminders",
        json={"parent_ids": ["parent-1", "parent-3"]},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["selected_parent_ids"] == ["parent-1", "parent-3"]
    assert body["generated_invoice_artifacts"] == 0
