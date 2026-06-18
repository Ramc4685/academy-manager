"""Admin composition tenant-scope hardening tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.composition.admin import compose_admin
from backend.v2.shared.config.settings import get_settings
from backend.v2.shared.tenancy.context import tenant_scope


class _NoopStripe:
    pass


class _FakeReconciliationStripe:
    def __init__(
        self,
        *,
        invoice: dict[str, Any] | None = None,
        payment_intent: dict[str, Any] | None = None,
    ) -> None:
        self.invoice = invoice
        self.payment_intent = payment_intent

    async def retrieve_invoice(self, stripe_invoice_id: str) -> dict[str, Any]:
        assert self.invoice is not None
        assert self.invoice["id"] == stripe_invoice_id
        return self.invoice

    async def retrieve_payment_intent(self, stripe_payment_intent_id: str) -> dict[str, Any]:
        assert self.payment_intent is not None
        assert self.payment_intent["id"] == stripe_payment_intent_id
        return self.payment_intent


def _admin_use_cases(db: Any):
    return compose_admin(
        db,
        outbox=object(),  # type: ignore[arg-type]
        idempotency_store=object(),  # type: ignore[arg-type]
        stripe=_NoopStripe(),  # type: ignore[arg-type]
    )


def _admin_use_cases_with_stripe(db: Any, stripe: Any):
    return compose_admin(
        db,
        outbox=object(),  # type: ignore[arg-type]
        idempotency_store=object(),  # type: ignore[arg-type]
        stripe=stripe,  # type: ignore[arg-type]
    )


@pytest.fixture
def mongo_db(monkeypatch):
    mongomock_motor = pytest.importorskip("mongomock_motor")
    monkeypatch.delenv("V2_DEFAULT_ACADEMY_ID", raising=False)
    monkeypatch.delenv("DEFAULT_ACADEMY_ID", raising=False)
    get_settings.cache_clear()
    try:
        client = mongomock_motor.AsyncMongoMockClient()
        yield client["test_db"]
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_admin_audit_logs_use_request_tenant_not_default(mongo_db) -> None:
    await mongo_db["audit_logs"].insert_many(
        [
            {
                "audit_id": "audit-request",
                "academy_id": "request-acad",
                "actor_id": "admin-1",
                "action": "billing.viewed",
                "entity_type": "invoice",
                "entity_id": "inv-1",
                "created_at": datetime(2026, 6, 16, tzinfo=UTC),
            },
            {
                "audit_id": "audit-default",
                "academy_id": "default-academy",
                "actor_id": "admin-2",
                "action": "billing.viewed",
                "entity_type": "invoice",
                "entity_id": "inv-2",
                "created_at": datetime(2026, 6, 15, tzinfo=UTC),
            },
        ]
    )

    admin = _admin_use_cases(mongo_db)
    with tenant_scope("request-acad"):
        rows = await admin.list_audit_logs()

    assert [row["audit_id"] for row in rows] == ["audit-request"]


@pytest.mark.asyncio
async def test_admin_invoice_detail_uses_request_tenant_not_default(mongo_db) -> None:
    now = datetime(2026, 6, 16, tzinfo=UTC)
    await mongo_db["invoices"].insert_many(
        [
            {
                "invoice_id": "inv-shared",
                "invoice_number": "REQ-001",
                "academy_id": "request-acad",
                "parent_id": "parent-1",
                "student_id": "student-1",
                "enrollment_id": "enr-1",
                "period": "2026-06",
                "status": "open",
                "total_cents": 10000,
                "balance_due_cents": 4000,
                "currency": "usd",
                "due_date": now,
                "created_at": now,
                "updated_at": now,
            },
            {
                "invoice_id": "inv-shared",
                "invoice_number": "DEFAULT-001",
                "academy_id": "default-academy",
                "parent_id": "parent-2",
                "student_id": "student-2",
                "enrollment_id": "enr-2",
                "period": "2026-06",
                "status": "open",
                "total_cents": 99999,
                "balance_due_cents": 99999,
                "currency": "usd",
                "due_date": now,
                "created_at": now,
                "updated_at": now,
            },
        ]
    )
    await mongo_db["invoice_lines"].insert_one(
        {
            "line_id": "line-request",
            "academy_id": "request-acad",
            "invoice_id": "inv-shared",
            "description": "Request academy tuition",
            "amount_cents": 10000,
        }
    )

    admin = _admin_use_cases(mongo_db)
    with tenant_scope("request-acad"):
        detail = await admin.get_billing_invoice_detail("inv-shared")

    assert detail["invoice_number"] == "REQ-001"
    assert detail["due_amount_cents"] == 4000
    assert detail["lines"] == [
        {
            "line_id": "line-request",
            "invoice_id": "inv-shared",
            "description": "Request academy tuition",
            "amount_cents": 10000,
        }
    ]


@pytest.mark.asyncio
async def test_admin_invoice_detail_payment_fallback_uses_request_tenant(mongo_db) -> None:
    now = datetime(2026, 6, 16, tzinfo=UTC)
    await mongo_db["payments"].insert_many(
        [
            {
                "payment_id": "pay-shared",
                "invoice_number": "REQ-PAY-001",
                "academy_id": "request-acad",
                "parent_id": "parent-1",
                "student_id": "student-1",
                "period": "2026-06",
                "status": "pending",
                "amount_cents": 12000,
                "paid_amount_cents": 2000,
                "balance_due_cents": 10000,
                "created_at": now,
            },
            {
                "payment_id": "pay-shared",
                "invoice_number": "DEFAULT-PAY-001",
                "academy_id": "default-academy",
                "parent_id": "parent-2",
                "student_id": "student-2",
                "period": "2026-06",
                "status": "succeeded",
                "amount_cents": 99999,
                "paid_amount_cents": 99999,
                "balance_due_cents": 0,
                "created_at": now,
            },
        ]
    )

    admin = _admin_use_cases(mongo_db)
    with tenant_scope("request-acad"):
        detail = await admin.get_billing_invoice_detail("pay-shared")

    assert detail["invoice_number"] == "REQ-PAY-001"
    assert detail["due_amount_cents"] == 10000
    assert detail["paid_amount_cents"] == 2000


@pytest.mark.asyncio
async def test_admin_invoice_artifact_write_enforces_request_tenant_ownership(mongo_db) -> None:
    now = datetime(2026, 6, 16, tzinfo=UTC)
    await mongo_db["invoices"].insert_one(
        {
            "invoice_id": "inv-request",
            "invoice_number": "REQ-002",
            "academy_id": "request-acad",
            "parent_id": "parent-1",
            "student_id": "student-1",
            "enrollment_id": "enr-1",
            "period": "2026-06",
            "status": "open",
            "total_cents": 10000,
            "balance_due_cents": 4000,
            "currency": "usd",
            "due_date": now,
            "created_at": now,
            "updated_at": now,
        }
    )

    admin = _admin_use_cases(mongo_db)
    with tenant_scope("request-acad"):
        result = await admin.generate_billing_invoice_artifact("inv-request", "invoice_pdf")

    artifact = await mongo_db["billing_artifacts"].find_one(
        {"academy_id": "request-acad", "artifact_id": result["artifact_id"]}
    )
    invoice = await mongo_db["invoices"].find_one(
        {"academy_id": "request-acad", "invoice_id": "inv-request"}
    )
    default_artifact = await mongo_db["billing_artifacts"].find_one(
        {"academy_id": "default-academy", "artifact_id": result["artifact_id"]}
    )

    assert artifact is not None
    assert default_artifact is None
    assert invoice is not None
    assert invoice["invoice_pdf_artifact_id"] == result["artifact_id"]


@pytest.mark.asyncio
async def test_admin_payment_artifact_write_enforces_request_tenant_ownership(mongo_db) -> None:
    now = datetime(2026, 6, 16, tzinfo=UTC)
    await mongo_db["payments"].insert_many(
        [
            {
                "payment_id": "pay-shared",
                "invoice_number": "REQ-PAY-001",
                "academy_id": "request-acad",
                "parent_id": "parent-1",
                "student_id": "student-1",
                "period": "2026-06",
                "status": "pending",
                "amount_cents": 10000,
                "created_at": now,
                "updated_at": now,
            },
            {
                "payment_id": "pay-shared",
                "invoice_number": "DEFAULT-PAY-001",
                "academy_id": "default-academy",
                "parent_id": "parent-2",
                "student_id": "student-2",
                "period": "2026-06",
                "status": "pending",
                "amount_cents": 99999,
                "created_at": now,
                "updated_at": now,
            },
        ]
    )

    admin = _admin_use_cases(mongo_db)
    with tenant_scope("request-acad"):
        result = await admin.generate_billing_invoice_artifact("pay-shared", "receipt")

    artifact = await mongo_db["billing_artifacts"].find_one(
        {"academy_id": "request-acad", "artifact_id": result["artifact_id"]}
    )
    request_payment = await mongo_db["payments"].find_one(
        {"academy_id": "request-acad", "payment_id": "pay-shared"}
    )
    default_payment = await mongo_db["payments"].find_one(
        {"academy_id": "default-academy", "payment_id": "pay-shared"}
    )

    assert artifact is not None
    assert request_payment is not None
    assert request_payment["receipt_artifact_id"] == result["artifact_id"]
    assert default_payment is not None
    assert "receipt_artifact_id" not in default_payment


@pytest.mark.asyncio
async def test_admin_dues_followup_uses_request_tenant_not_default(mongo_db) -> None:
    now = datetime(2026, 6, 16, tzinfo=UTC)
    await mongo_db["payments"].insert_many(
        [
            {
                "payment_id": "pay-request",
                "academy_id": "request-acad",
                "parent_id": "parent-request",
                "student_id": "student-request",
                "status": "pending",
                "amount_cents": 12000,
                "created_at": now,
            },
            {
                "payment_id": "pay-default",
                "academy_id": "default-academy",
                "parent_id": "parent-default",
                "student_id": "student-default",
                "status": "pending",
                "amount_cents": 99000,
                "created_at": now,
            },
        ]
    )
    await mongo_db["users"].insert_many(
        [
            {
                "academy_id": "request-acad",
                "user_id": "parent-request",
                "display_name": "Request Parent",
                "email": "request@example.com",
            },
            {
                "academy_id": "default-academy",
                "user_id": "parent-default",
                "display_name": "Default Parent",
                "email": "default@example.com",
            },
        ]
    )

    admin = _admin_use_cases(mongo_db)
    with tenant_scope("request-acad"):
        rows = await admin.list_dues_followup()

    assert [row["parent_id"] for row in rows] == ["parent-request"]
    assert rows[0]["parent_name"] == "Request Parent"
    assert rows[0]["total_due_cents"] == 12000


@pytest.mark.asyncio
async def test_admin_dues_followup_uses_open_ledger_invoices_without_legacy_payments(
    mongo_db,
) -> None:
    now = datetime(2026, 6, 16, tzinfo=UTC)
    await mongo_db["invoices"].insert_many(
        [
            {
                "invoice_id": "inv-open",
                "invoice_number": "REQ-OPEN-001",
                "academy_id": "request-acad",
                "parent_id": "parent-request",
                "student_id": "student-request",
                "period": "2026-06",
                "status": "open",
                "total_cents": 12000,
                "balance_due_cents": 12000,
                "currency": "usd",
                "due_date": now,
                "created_at": now,
                "updated_at": now,
            },
            {
                "invoice_id": "inv-partial",
                "academy_id": "request-acad",
                "parent_id": "parent-request",
                "student_id": "student-request",
                "period": "2026-06",
                "status": "partially_paid",
                "total_cents": 10000,
                "balance_due_cents": 4000,
                "currency": "usd",
                "due_date": now,
                "created_at": now,
                "updated_at": now,
            },
            {
                "invoice_id": "inv-default",
                "academy_id": "default-academy",
                "parent_id": "parent-default",
                "student_id": "student-default",
                "period": "2026-06",
                "status": "open",
                "total_cents": 99000,
                "balance_due_cents": 99000,
                "currency": "usd",
                "due_date": now,
                "created_at": now,
                "updated_at": now,
            },
        ]
    )
    await mongo_db["users"].insert_one(
        {
            "academy_id": "request-acad",
            "user_id": "parent-request",
            "display_name": "Request Parent",
            "email": "request@example.com",
        }
    )

    admin = _admin_use_cases(mongo_db)
    with tenant_scope("request-acad"):
        rows = await admin.list_dues_followup()

    assert [row["parent_id"] for row in rows] == ["parent-request"]
    assert rows[0]["parent_name"] == "Request Parent"
    assert rows[0]["email"] == "request@example.com"
    assert rows[0]["pending_count"] == 2
    assert rows[0]["total_due_cents"] == 16000


@pytest.mark.asyncio
async def test_admin_attendance_export_uses_request_tenant_not_default(mongo_db) -> None:
    now = datetime(2026, 6, 16, tzinfo=UTC)
    await mongo_db["attendance"].insert_many(
        [
            {
                "attendance_id": "att-request",
                "academy_id": "request-acad",
                "session_id": "sess-request",
                "student_id": "student-request",
                "status": "present",
                "marked_at": now,
            },
            {
                "attendance_id": "att-default",
                "academy_id": "default-academy",
                "session_id": "sess-default",
                "student_id": "student-default",
                "status": "present",
                "marked_at": now,
            },
        ]
    )

    admin = _admin_use_cases(mongo_db)
    with tenant_scope("request-acad"):
        csv_text = await admin.export_report_csv("attendance")

    assert "att-request" in csv_text
    assert "att-default" not in csv_text


@pytest.mark.asyncio
async def test_admin_pending_payments_export_uses_request_tenant_not_default(mongo_db) -> None:
    now = datetime(2026, 6, 16, tzinfo=UTC)
    await mongo_db["payments"].insert_many(
        [
            {
                "payment_id": "pay-request",
                "academy_id": "request-acad",
                "parent_id": "parent-request",
                "student_id": "student-request",
                "status": "pending",
                "amount_cents": 12000,
                "created_at": now,
            },
            {
                "payment_id": "pay-default",
                "academy_id": "default-academy",
                "parent_id": "parent-default",
                "student_id": "student-default",
                "status": "pending",
                "amount_cents": 99000,
                "created_at": now,
            },
        ]
    )

    admin = _admin_use_cases(mongo_db)
    with tenant_scope("request-acad"):
        csv_text = await admin.export_report_csv("pending-payments")

    assert "pay-request" in csv_text
    assert "pay-default" not in csv_text


@pytest.mark.asyncio
async def test_admin_revenue_export_includes_ledger_payments(mongo_db) -> None:
    now = datetime(2026, 6, 16, tzinfo=UTC)
    await mongo_db["ledger_payments"].insert_many(
        [
            {
                "payment_id": "ledger-request",
                "academy_id": "request-acad",
                "parent_id": "parent-request",
                "status": "succeeded",
                "amount_cents": 12000,
                "currency": "usd",
                "created_at": now,
            },
            {
                "payment_id": "ledger-default",
                "academy_id": "default-academy",
                "parent_id": "parent-default",
                "status": "succeeded",
                "amount_cents": 99000,
                "currency": "usd",
                "created_at": now,
            },
        ]
    )

    admin = _admin_use_cases(mongo_db)
    with tenant_scope("request-acad"):
        csv_text = await admin.export_report_csv("revenue")

    assert csv_text == "month,revenue_cents\r\n2026-06,12000\r\n"


@pytest.mark.asyncio
async def test_admin_payments_recent_suppresses_matching_legacy_projection(mongo_db) -> None:
    now = datetime(2026, 6, 16, tzinfo=UTC)
    await mongo_db["ledger_payments"].insert_one(
        {
            "payment_id": "ledger-subscription",
            "academy_id": "request-acad",
            "parent_id": "parent-request",
            "status": "succeeded",
            "amount_cents": 12000,
            "currency": "usd",
            "stripe_invoice_id": "in_subscription_paid",
            "stripe_payment_intent_id": "in_subscription_paid",
            "created_at": now,
        }
    )
    await mongo_db["payments"].insert_one(
        {
            "payment_id": "legacy-subscription-projection",
            "academy_id": "request-acad",
            "parent_id": "parent-request",
            "status": "succeeded",
            "amount_cents": 12000,
            "currency": "usd",
            "stripe_payment_intent_id": "in_subscription_paid",
            "created_at": now,
            "updated_at": now,
        }
    )

    admin = _admin_use_cases(mongo_db)
    with tenant_scope("request-acad"):
        rows = await admin.list_payments_recent()

    assert [row["payment_id"] for row in rows] == ["ledger-subscription"]


@pytest.mark.asyncio
async def test_admin_payments_recent_returns_invoice_rows_without_legacy_payments(
    mongo_db,
) -> None:
    now = datetime(2026, 6, 17, tzinfo=UTC)
    await mongo_db["invoices"].insert_many(
        [
            {
                "invoice_id": "inv-open",
                "invoice_number": "REQ-OPEN-001",
                "academy_id": "request-acad",
                "parent_id": "parent-request",
                "student_id": "student-request",
                "enrollment_id": "enr-request",
                "period": "2026-06",
                "status": "open",
                "subtotal_cents": 12000,
                "discount_cents": 1000,
                "total_cents": 11000,
                "balance_due_cents": 11000,
                "currency": "usd",
                "due_date": now,
                "created_at": now,
                "updated_at": now,
            },
            {
                "invoice_id": "inv-paid",
                "invoice_number": "REQ-PAID-001",
                "academy_id": "request-acad",
                "parent_id": "parent-request",
                "student_id": "student-request",
                "enrollment_id": "enr-request",
                "period": "2026-05",
                "status": "paid",
                "subtotal_cents": 12000,
                "discount_cents": 0,
                "total_cents": 12000,
                "balance_due_cents": 0,
                "currency": "usd",
                "stripe_invoice_id": "in_paid",
                "created_at": now.replace(day=16),
                "updated_at": now,
            },
        ]
    )

    admin = _admin_use_cases(mongo_db)
    with tenant_scope("request-acad"):
        rows = await admin.list_payments_recent()

    assert [row["payment_id"] for row in rows] == ["inv-open", "inv-paid"]
    assert rows[0]["status"] == "pending"
    assert rows[0]["amount_cents"] == 12000
    assert rows[0]["discount_cents"] == 1000
    assert rows[0]["final_amount_cents"] == 11000
    assert rows[0]["balance_due_cents"] == 11000
    assert rows[0]["paid_amount_cents"] == 0
    assert rows[0]["invoice_number"] == "REQ-OPEN-001"
    assert rows[1]["status"] == "paid"
    assert rows[1]["paid_amount_cents"] == 12000
    assert rows[1]["stripe_invoice_id"] == "in_paid"


@pytest.mark.asyncio
async def test_admin_payments_recent_includes_failed_payment_attempts(mongo_db) -> None:
    now = datetime(2026, 6, 17, tzinfo=UTC)
    await mongo_db["payment_attempts"].insert_many(
        [
            {
                "attempt_id": "attempt-request",
                "idempotency_key": "invoice-checkout-failed:inv-request:pi-request",
                "academy_id": "request-acad",
                "invoice_id": "inv-request",
                "parent_id": "parent-request",
                "amount_cents": 1242,
                "currency": "usd",
                "status": "failed",
                "failure_code": "insufficient_funds",
                "failure_message": "Your card has insufficient funds.",
                "stripe_payment_intent_id": "pi-request",
                "stripe_checkout_session_id": "cs-request",
                "created_at": now,
            },
            {
                "attempt_id": "attempt-default",
                "idempotency_key": "invoice-checkout-failed:inv-default:pi-default",
                "academy_id": "default-academy",
                "invoice_id": "inv-default",
                "parent_id": "parent-default",
                "amount_cents": 9999,
                "currency": "usd",
                "status": "failed",
                "failure_code": "card_declined",
                "stripe_payment_intent_id": "pi-default",
                "stripe_checkout_session_id": "cs-default",
                "created_at": now,
            },
        ]
    )

    admin = _admin_use_cases(mongo_db)
    with tenant_scope("request-acad"):
        rows = await admin.list_payments_recent()

    assert len(rows) == 1
    assert rows[0]["payment_id"] == "attempt-request"
    assert rows[0]["invoice_number"] == "inv-request"
    assert rows[0]["status"] == "failed"
    assert rows[0]["amount_cents"] == 1242
    assert rows[0]["balance_due_cents"] == 1242
    assert rows[0]["paid_amount_cents"] == 0
    assert rows[0]["payment_method"] == "stripe_checkout"
    assert rows[0]["stripe_payment_intent_id"] == "pi-request"
    assert rows[0]["stripe_checkout_session_id"] == "cs-request"
    assert rows[0]["reconciliation_status"] == "insufficient_funds"


@pytest.mark.asyncio
async def test_admin_billing_webhook_queue_uses_request_tenant(mongo_db) -> None:
    now = datetime(2026, 6, 17, tzinfo=UTC)
    await mongo_db["stripe_webhook_events"].insert_many(
        [
            {
                "event_id": "evt-request",
                "event_type": "invoice.paid",
                "academy_id": "request-acad",
                "status": "quarantined",
                "object_id": "in-request",
                "object_type": "invoice",
                "received_at": now,
                "last_attempt_at": now,
                "retry_count": 2,
                "error_message": "duplicate obligation",
            },
            {
                "event_id": "evt-request-failed",
                "event_type": "invoice.payment_failed",
                "academy_id": "request-acad",
                "status": "failed",
                "object_id": "in-failed",
                "object_type": "invoice",
                "received_at": now,
                "last_attempt_at": now,
                "retry_count": 1,
                "error_message": "transient error",
            },
            {
                "event_id": "evt-default",
                "event_type": "invoice.paid",
                "academy_id": "default-academy",
                "status": "quarantined",
                "object_id": "in-default",
                "object_type": "invoice",
                "received_at": now,
                "last_attempt_at": now,
                "retry_count": 1,
                "error_message": "wrong tenant",
            },
        ]
    )

    admin = _admin_use_cases(mongo_db)
    with tenant_scope("request-acad"):
        rows = await admin.list_billing_webhook_events(status="quarantined", limit=10)

    assert [row["event_id"] for row in rows] == ["evt-request"]
    assert rows[0]["error_message"] == "duplicate obligation"


@pytest.mark.asyncio
async def test_billing_reconciliation_detects_orphan_stripe_payment(mongo_db) -> None:
    stripe = _FakeReconciliationStripe(
        payment_intent={
            "id": "pi_orphan",
            "status": "succeeded",
            "amount": 7000,
            "customer": "cus_parent",
        }
    )

    admin = _admin_use_cases_with_stripe(mongo_db, stripe)
    with tenant_scope("request-acad"):
        report = await admin.get_billing_reconciliation_report(payment_intent_id="pi_orphan")

    assert report["result"] == "ORPHAN_STRIPE_PAYMENT"
    assert report["payment_intent_id"] == "pi_orphan"
    assert report["stripe_customer_id"] == "cus_parent"
    assert report["local_invoice_id"] is None
    assert report["ledger_payment_id"] is None
    assert report["mismatches"][0]["code"] == "ORPHAN_STRIPE_PAYMENT"


@pytest.mark.asyncio
async def test_billing_reconciliation_detects_duplicate_obligation(mongo_db) -> None:
    now = datetime(2026, 6, 17, tzinfo=UTC)
    await mongo_db["invoices"].insert_one(
        {
            "invoice_id": "inv-existing",
            "academy_id": "request-acad",
            "parent_id": "parent-1",
            "student_id": "student-1",
            "enrollment_id": "enroll-1",
            "period": "2026-06",
            "status": "paid",
            "total_cents": 7000,
            "balance_due_cents": 0,
            "currency": "usd",
            "stripe_invoice_id": "in_existing_paid",
            "created_at": now,
            "updated_at": now,
        }
    )
    stripe = _FakeReconciliationStripe(
        invoice={
            "id": "in_duplicate",
            "status": "paid",
            "paid": True,
            "amount_paid": 7000,
            "customer": "cus_parent",
            "payment_intent": "pi_duplicate",
            "metadata": {
                "academy_id": "request-acad",
                "parent_id": "parent-1",
                "student_id": "student-1",
                "enrollment_id": "enroll-1",
                "period": "2026-06",
            },
        },
        payment_intent={
            "id": "pi_duplicate",
            "status": "succeeded",
            "amount": 7000,
            "customer": "cus_parent",
        },
    )

    admin = _admin_use_cases_with_stripe(mongo_db, stripe)
    with tenant_scope("request-acad"):
        report = await admin.get_billing_reconciliation_report(stripe_invoice_id="in_duplicate")

    assert report["result"] == "DUPLICATE_OBLIGATION"
    assert report["stripe_invoice_id"] == "in_duplicate"
    assert report["local_invoice_id"] == "inv-existing"
    assert report["mismatches"][0]["code"] == "DUPLICATE_OBLIGATION"
    assert report["mismatches"][0]["stripe_value"] == "in_duplicate"
    assert report["mismatches"][0]["local_value"] == "in_existing_paid"


@pytest.mark.asyncio
async def test_admin_revenue_export_dedupes_legacy_subscription_projection(mongo_db) -> None:
    now = datetime(2026, 6, 16, tzinfo=UTC)
    await mongo_db["ledger_payments"].insert_one(
        {
            "payment_id": "ledger-subscription",
            "academy_id": "request-acad",
            "parent_id": "parent-request",
            "status": "succeeded",
            "amount_cents": 12000,
            "currency": "usd",
            "stripe_invoice_id": "in_subscription_paid",
            "stripe_payment_intent_id": "in_subscription_paid",
            "created_at": now,
        }
    )
    await mongo_db["payments"].insert_one(
        {
            "payment_id": "legacy-subscription-projection",
            "academy_id": "request-acad",
            "parent_id": "parent-request",
            "status": "succeeded",
            "amount_cents": 12000,
            "currency": "usd",
            "stripe_payment_intent_id": "in_subscription_paid",
            "created_at": now,
            "updated_at": now,
        }
    )

    admin = _admin_use_cases(mongo_db)
    with tenant_scope("request-acad"):
        csv_text = await admin.export_report_csv("revenue")

    assert csv_text == "month,revenue_cents\r\n2026-06,12000\r\n"


@pytest.mark.asyncio
async def test_admin_report_export_rejects_unknown_report_name(mongo_db) -> None:
    admin = _admin_use_cases(mongo_db)

    with tenant_scope("request-acad"), pytest.raises(ValueError, match="unknown report export"):
        await admin.export_report_csv("all-tenants")


@pytest.mark.asyncio
async def test_admin_enrollment_funnel_uses_request_tenant_not_default(mongo_db) -> None:
    now = datetime(2026, 6, 16, tzinfo=UTC)
    await mongo_db["onboarding_applications"].insert_many(
        [
            {
                "application_id": "app-request",
                "academy_id": "request-acad",
                "status": "APPROVED",
                "created_at": now,
            },
            {
                "application_id": "app-default",
                "academy_id": "default-academy",
                "status": "DRAFT",
                "created_at": now,
            },
        ]
    )

    admin = _admin_use_cases(mongo_db)
    with tenant_scope("request-acad"):
        result = await admin.get_enrollment_funnel(None)

    assert result.confirmed == 1
    assert result.leads == 0
